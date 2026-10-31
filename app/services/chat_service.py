# app/services/chat_service.py
#
# PNEC chatbot proxy. Despite the historical "/api/gemini" route URL,
# this service calls Groq FIRST (llama-3.3-70b-versatile) and only
# falls back to Gemini (gemini-2.5-flash-lite) if Groq is unconfigured
# or errors out.
#
# Why Groq is primary: its free tier handles roughly 14,400 chatbot
# requests per day, which is much higher than Gemini's free quota.
# We switched the chatbot to Groq once real resident traffic started
# hitting Gemini's rate limits.
#
# The route file is still named app/routes/gemini.py and the URL is
# still /api/gemini. The deployed frontend hits that URL in 4 places
# (assets/js/api/gemini.js, poway-page-enhancements.js, etc.) so
# renaming the endpoint would need a coordinated FE/BE change.

import requests
from flask import current_app


def generate_chat_response(system_prompt, user_message, history=None, image_data=None, image_mime_type='image/jpeg'):
    system_prompt = (system_prompt or '').strip()
    user_message = (user_message or '').strip()
    if not user_message:
        return None, 'MISSING_MESSAGE'

    # Try Groq first (14,400 req/day on the free tier, OpenAI-compatible API)
    groq_key = current_app.config.get('GROQ_API_KEY')
    if groq_key:
        text, err = _call_groq(groq_key, system_prompt, user_message, history)
        if text:
            return text, None
        current_app.logger.warning('Groq failed (%s), falling back to Gemini', err)

    # Fall back to Gemini
    gemini_key = current_app.config.get('GEMINI_API_KEY')
    if not gemini_key:
        return None, 'GEMINI_NOT_CONFIGURED'

    return _call_gemini(gemini_key, system_prompt, user_message, history, image_data, image_mime_type)


# ─── Groq ─────────────────────────────────────────────────────────────────────

def _call_groq(api_key, system_prompt, user_message, history):
    model = current_app.config.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
    endpoint = f"{current_app.config.get('GROQ_API_URL', 'https://api.groq.com/openai/v1')}/chat/completions"

    messages = [{'role': 'system', 'content': system_prompt}]
    for turn in (history or [])[-8:]:
        if not isinstance(turn, dict):
            continue
        role = turn.get('role')
        content = str(turn.get('content') or '').strip()
        if content and role in ('user', 'assistant'):
            messages.append({'role': role, 'content': content[:2000]})
    messages.append({'role': 'user', 'content': user_message})

    try:
        response = requests.post(
            endpoint,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': model, 'messages': messages, 'temperature': 0.6, 'max_tokens': 2000},
            timeout=20,
        )
    except requests.RequestException as exc:
        return None, f'network error: {exc}'

    if response.status_code >= 400:
        try:
            detail = response.json().get('error', {}).get('message', response.text[:200])
        except ValueError:
            detail = response.text[:200]
        return None, f'HTTP {response.status_code}: {detail}'

    try:
        data = response.json()
        text = data['choices'][0]['message']['content'].strip()
        return (text or None), (None if text else 'empty response')
    except (ValueError, KeyError, IndexError):
        return None, 'bad response shape'


# ─── Gemini ───────────────────────────────────────────────────────────────────

def _call_gemini(api_key, system_prompt, user_message, history, image_data=None, image_mime_type='image/jpeg'):
    model = current_app.config.get('GEMINI_MODEL', 'gemini-2.5-flash-lite')
    api_base = current_app.config.get('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta').rstrip('/')
    endpoint = f'{api_base}/models/{model}:generateContent'

    payload = {
        'systemInstruction': {'parts': [{'text': system_prompt}]},
        'contents': _build_gemini_contents(history, user_message, image_data, image_mime_type),
        'generationConfig': {'temperature': 0.6, 'topP': 0.92, 'maxOutputTokens': 2000},
    }

    try:
        response = requests.post(endpoint, params={'key': api_key}, json=payload, timeout=20)
    except requests.RequestException as exc:
        current_app.logger.warning('Gemini network error: %s', exc)
        return None, {'code': 'GEMINI_NETWORK_ERROR', 'detail': str(exc)}

    if response.status_code >= 400:
        detail = _extract_gemini_error(response)
        current_app.logger.warning('Gemini API error %s: %s', response.status_code, detail)
        return None, {'code': 'GEMINI_API_ERROR', 'detail': f'Gemini API returned {response.status_code}: {detail}'}

    try:
        data = response.json()
    except ValueError:
        return None, {'code': 'GEMINI_BAD_RESPONSE', 'detail': 'Non-JSON response from Gemini'}

    text = _extract_gemini_text(data)
    if not text:
        return None, {'code': 'GEMINI_EMPTY_RESPONSE', 'detail': 'Gemini returned no answer text'}

    return text, None


def _extract_gemini_text(data):
    candidates = data.get('candidates') if isinstance(data, dict) else None
    if not candidates:
        return ''
    parts = candidates[0].get('content', {}).get('parts', [])
    return ''.join(part.get('text', '') for part in parts if isinstance(part, dict)).strip()


def _extract_gemini_error(response):
    try:
        data = response.json()
    except ValueError:
        return response.text[:300] or 'No error details.'
    if not isinstance(data, dict):
        return 'Unexpected error response.'
    error = data.get('error')
    if isinstance(error, dict):
        return error.get('message') or error.get('status') or 'No error details.'
    return data.get('message') or data.get('detail') or 'No error details.'


def _build_gemini_contents(history, user_message, image_data=None, image_mime_type='image/jpeg'):
    contents = []
    for turn in (history or [])[-8:]:
        if not isinstance(turn, dict):
            continue
        role = turn.get('role')
        content = str(turn.get('content') or '').strip()
        if not content:
            continue
        contents.append({'role': 'model' if role == 'assistant' else 'user', 'parts': [{'text': content[:2000]}]})

    last_parts = [{'text': user_message}]
    if image_data:
        last_parts.append({'inline_data': {'mime_type': image_mime_type, 'data': image_data}})
    contents.append({'role': 'user', 'parts': last_parts})
    return contents
