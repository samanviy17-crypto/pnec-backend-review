# app/routes/cms_ai.py
# Responsibility: AI-assisted CMS — given a prompt + the current page state +
# the available section schemas, ask Groq (Llama 3.3 70B by default) to emit
# a valid section instance the editor can drop into the page. Uses the same
# Groq key the chatbot uses (GROQ_API_KEY in .env).

import json
import os

import requests
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role


cms_ai_bp = Blueprint('cms_ai', __name__)

# Cap prompt length to avoid runaway Groq spend on a malformed/runaway request.
# 4k chars is plenty for "describe a 5-section page with…" prompts.
_MAX_PROMPT_LEN = 4000


def _validate_prompt(body, key='prompt'):
    """Return (prompt, error_response) — exactly one is non-None."""
    prompt = (body.get(key) or '').strip()
    if not prompt:
        return None, error_response('VALIDATION_FAILED', 400, {'detail': f'{key} is required'})
    if len(prompt) > _MAX_PROMPT_LEN:
        return None, error_response('VALIDATION_FAILED', 400,
            {'detail': f'{key} too long (max {_MAX_PROMPT_LEN} chars)'})
    return prompt, None


def _groq_call(system, user, json_mode=True):
    api_key = current_app.config.get('GROQ_API_KEY') or os.environ.get('GROQ_API_KEY')
    if not api_key:
        return None, 'GROQ_API_KEY not configured'
    model = current_app.config.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
    endpoint = (current_app.config.get('GROQ_API_URL', 'https://api.groq.com/openai/v1').rstrip('/')
                + '/chat/completions')
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user',   'content': user},
        ],
        'temperature': 0.4,
        'max_tokens': 2000,
    }
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    try:
        res = requests.post(
            endpoint,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        return None, f'network error: {exc}'
    if res.status_code >= 400:
        try:
            detail = res.json().get('error', {}).get('message', res.text[:300])
        except ValueError:
            detail = res.text[:300]
        return None, f'HTTP {res.status_code}: {detail}'
    try:
        data = res.json()
        return data['choices'][0]['message']['content'].strip(), None
    except (ValueError, KeyError, IndexError) as exc:
        return None, f'bad response shape: {exc}'


def _build_prompt(prompt, registry_types, page_context):
    system = (
        "You are a layout assistant for a small nonprofit's website CMS. "
        "Given the user's intent and the available section types (with their "
        "JSON schemas), respond with a SINGLE valid JSON object describing one "
        "section to add. The JSON must contain exactly: "
        '{"type": "<one of the available types>", "settings": {...}, '
        '"blocks": [{"type": "...", "settings": {...}}, ...]}. '
        "Only include `blocks` if the section type defines block schemas. Use the "
        "field ids from the schema. Keep copy concise, friendly, and appropriate "
        "for a community emergency-preparedness organization. Output ONLY the "
        "JSON object — no Markdown fences, no prose, no explanation."
    )
    user = (
        "AVAILABLE SECTION TYPES:\n" + json.dumps(registry_types, indent=2) +
        "\n\nCURRENT PAGE STATE (read-only context, do not duplicate):\n" +
        json.dumps(page_context or {}, indent=2) +
        "\n\nUSER REQUEST:\n" + prompt +
        "\n\nRespond with one JSON object only."
    )
    return system, user


def _parse_response(text):
    text = (text or '').strip()
    if text.startswith('```'):
        # Strip fences if model added them
        first = text.find('\n')
        if first > 0:
            text = text[first + 1:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    start = text.find('{')
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except (ValueError, TypeError):
                    return None
    return None


@cms_ai_bp.route('/cms/ai/placeholder-image', methods=['POST'])
@requires_role('admin')
def generate_placeholder_image():
    """Turn a short description into a usable image URL.
    Body: {prompt, width?=1200, height?=800}
    Returns: {url, alt}

    Strategy:
      1. Ask Groq to polish the user's prompt into a concise, neutral
         photo-prompt (no proper names, no copyright). Discards any
         attempt to ask for a logo / specific person.
      2. Hand the polished prompt off to https://image.pollinations.ai/
         which returns an actual generated PNG keyed by the prompt
         (free, no API key, deterministic-ish per prompt). Pollinations
         lets us pick a width/height and a flag to suppress its watermark.
      3. Generate an alt-text suggestion in the same Groq call so the
         frontend can offer one-click "set alt text" too.
    No image is uploaded — we just return the URL string.
    """
    body = request.get_json(silent=True) or {}
    prompt, err = _validate_prompt(body)
    if err:
        return err

    # Clamp dims to a sane range so a malicious caller can't request 100k px
    try:
        width  = max(64, min(int(body.get('width')  or 1200), 2400))
        height = max(64, min(int(body.get('height') or 800),  2400))
    except (TypeError, ValueError):
        width, height = 1200, 800

    # Ask Groq for a polished neutral prompt + alt
    system = (
        "You polish image-generation prompts for a small community-emergency-preparedness "
        "nonprofit website. The prompt becomes the URL slug for an AI image generator, so:\n"
        "- No people whose identity matters (no celebrities, no specific staff names).\n"
        "- No copyrighted characters or logos.\n"
        "- Prefer realistic photography style: well-lit, candid, daylight, community-feel.\n"
        "- 6–14 words. Be concrete (objects, setting, mood) not abstract.\n"
        "Reply ONLY a JSON object: "
        '{"image_prompt": "...", "alt": "..."}.'
    )
    user = f"USER ASKED FOR: {prompt}\nPolish to a neutral, ethical photo prompt and write alt text."
    text, err = _groq_call(system, user, json_mode=True)
    polished = prompt
    alt      = prompt
    if not err and text:
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                polished = (payload.get('image_prompt') or polished).strip()[:300]
                alt      = (payload.get('alt')          or alt).strip()[:200]
        except (ValueError, TypeError):
            pass

    # Pollinations URL — public, free, no key. `nologo=true` removes their stamp.
    # `seed` keyed off polished prompt makes the same prompt return the same image.
    from urllib.parse import quote
    seed = abs(hash(polished)) % 1_000_000
    url = (
        'https://image.pollinations.ai/prompt/'
        + quote(polished, safe='')
        + f'?width={width}&height={height}&nologo=true&seed={seed}'
    )
    return jsonify({'url': url, 'alt': alt, 'polished_prompt': polished}), 200


@cms_ai_bp.route('/cms/ai/alt-text', methods=['POST'])
@requires_role('admin')
def generate_alt_text():
    """Generate image alt text from a URL. Body: {image_url, context?}"""
    body = request.get_json(silent=True) or {}
    image_url = (body.get('image_url') or '').strip()
    if not image_url:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'image_url required'})
    ctx = (body.get('context') or '').strip()
    system = ('You write concise, descriptive alt text for images on a community '
              'emergency-preparedness nonprofit website (PNEC, Poway). Output ONLY '
              'the alt text, no quotes, under 120 characters. Describe what is '
              'visible, not metaphorical meaning.')
    user = (f'IMAGE URL: {image_url}\n' +
            (f'CONTEXT: {ctx}\n' if ctx else '') +
            'Write alt text.')
    text, err = _groq_call(system, user, json_mode=False)
    if err:
        return error_response('SERVER_ERROR', 502, {'detail': err})
    alt = (text or '').strip().strip('"\'').strip()[:200]
    return jsonify({'alt': alt}), 200


@cms_ai_bp.route('/cms/ai/page', methods=['POST'])
@requires_role('admin')
def generate_page():
    """Generate a multi-section page layout from a single prompt.
    Body: {prompt, page_slug?}
    Returns: {sections: [{type, settings, blocks?}, ...]} — caller adds them in order."""
    body = request.get_json(silent=True) or {}
    prompt, err = _validate_prompt(body)
    if err:
        return err
    reg = current_app.config.get('CMS_REGISTRY')
    if not reg:
        return error_response('SERVER_ERROR', 500, {'detail': 'cms registry not initialized'})
    types = reg.list_types()

    system = (
        "You build full landing-page layouts for a small nonprofit's website CMS "
        "(Poway Neighborhood Emergency Corps — community emergency preparedness). "
        "Given the user's prompt and the available section types, output a SINGLE "
        "valid JSON object: "
        '{"sections": [{"type": "<one of the available types>", "settings": {...}, '
        '"blocks": [{"type": "...", "settings": {...}}, ...]}, ...]}. '
        "Use 4-6 sections per page typically: a hero or cta_banner at top, then "
        "1-3 content sections (text_block, image_with_text, card_list, faq, gallery), "
        "and end with a contact_cta or another cta_banner. Use field ids from the "
        "schemas. Keep copy concise, friendly, factual — no emoji unless natural. "
        "Output ONLY the JSON, no Markdown fences, no prose."
    )
    user = (
        "AVAILABLE SECTION TYPES:\n" + json.dumps(types, indent=2) +
        "\n\nUSER PROMPT:\n" + prompt +
        "\n\nRespond with one JSON object containing a 'sections' array."
    )
    text, err = _groq_call(system, user)
    if err:
        return error_response('SERVER_ERROR', 502, {'detail': err})
    parsed = _parse_response(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get('sections'), list):
        return error_response('SERVER_ERROR', 502, {
            'detail': 'AI response did not contain a sections array',
            'raw': (text or '')[:1000],
        })

    out_sections = []
    for s in parsed['sections']:
        type_id = s.get('type')
        type_entry = reg.get(type_id)
        if not type_entry:
            continue
        schema = type_entry['schema']
        valid_keys = {f['id'] for f in (schema.get('settings') or [])}
        settings = {k: v for k, v in (s.get('settings') or {}).items() if k in valid_keys}
        valid_block_types = {b['type']: {f['id'] for f in (b.get('settings') or [])}
                             for b in (schema.get('blocks') or [])}
        blocks = []
        for b in (s.get('blocks') or []):
            bt = b.get('type')
            if bt not in valid_block_types:
                continue
            blocks.append({
                'type': bt,
                'settings': {k: v for k, v in (b.get('settings') or {}).items()
                             if k in valid_block_types[bt]},
            })
        section_obj = {'type': type_id, 'settings': settings}
        if blocks:
            section_obj['blocks'] = blocks
        out_sections.append(section_obj)

    if not out_sections:
        return error_response('SERVER_ERROR', 502, {
            'detail': 'AI returned no valid sections',
            'raw': (text or '')[:1000],
        })
    return jsonify({'sections': out_sections}), 200


@cms_ai_bp.route('/cms/ai/section', methods=['POST'])
@requires_role('admin')
def generate_section():
    body = request.get_json(silent=True) or {}
    prompt, err = _validate_prompt(body)
    if err:
        return err

    reg = current_app.config.get('CMS_REGISTRY')
    if not reg:
        return error_response('SERVER_ERROR', 500, {'detail': 'cms registry not initialized'})
    types = reg.list_types()

    system, user = _build_prompt(prompt, types, body.get('page_context'))
    text, err = _groq_call(system, user)
    if err:
        return error_response('SERVER_ERROR', 502, {'detail': f'AI request failed: {err}'})

    section = _parse_response(text)
    if not isinstance(section, dict) or 'type' not in section:
        return error_response('SERVER_ERROR', 502, {
            'detail': 'AI response did not contain a valid section JSON',
            'raw': (text or '')[:1000],
        })

    type_id = section.get('type')
    type_entry = reg.get(type_id)
    if not type_entry:
        return error_response('SERVER_ERROR', 502, {
            'detail': f'AI selected unknown type {type_id!r}',
            'raw': (text or '')[:1000],
        })

    schema = type_entry['schema']
    valid_keys = {f['id'] for f in (schema.get('settings') or [])}
    settings = {k: v for k, v in (section.get('settings') or {}).items() if k in valid_keys}

    valid_block_types = {b['type']: {f['id'] for f in (b.get('settings') or [])}
                         for b in (schema.get('blocks') or [])}
    out_blocks = []
    for b in (section.get('blocks') or []):
        bt = b.get('type')
        if bt not in valid_block_types:
            continue
        valid_block_keys = valid_block_types[bt]
        out_blocks.append({
            'type': bt,
            'settings': {k: v for k, v in (b.get('settings') or {}).items() if k in valid_block_keys},
        })

    result = {'type': type_id, 'settings': settings}
    if out_blocks:
        result['blocks'] = out_blocks
    return jsonify(result), 200
