# app/routes/admin_publish.py
# v3.15 / v3.17 — admin endpoints for the Live Theme Editor:
#   - GET  /api/admin/publish/health      server health: token, repo, Groq
#   - GET  /api/admin/publish/file        GET current content of a file from GitHub
#   - POST /api/admin/publish/file        commit a single file change to GitHub
#   - POST /api/admin/publish/files       commit a batch of file changes (atomic)
#   - POST /api/admin/publish/diff        compute unified diff (proposed vs HEAD)
#   - GET  /api/admin/publish/history     list recent commits for a path
#   - POST /api/admin/publish/rollback    revert a file to a specific commit
#   - GET  /api/admin/publish/status      latest workflow run status
#   - POST /api/admin/ai/section          generate page section HTML via Groq

import difflib
import os
from flask import Blueprint, jsonify, request, current_app

from app.services import github_publish_service as gh
from app.utils.errors import error_response

admin_publish_bp = Blueprint('admin_publish', __name__)


# ─── Defensive type coercion ───────────────────────────────────────
# 2026-05-13: previously the route used `(data.get('x') or '').strip()`
# which crashes with `AttributeError: 'dict' object has no attribute
# 'strip'` if the frontend sends a non-string by mistake. nginx then
# returns an HTML 500 page that the browser can't parse as JSON, and
# the user sees a cryptic "Unexpected token '<'" toast instead of a
# meaningful error. `_as_str` short-circuits that whole class of bug.

def _as_str(v, default=''):
    """Return v.strip() if v is a string, else the default. Survives
    None / dict / list / int / anything weird the frontend might send."""
    return v.strip() if isinstance(v, str) else default


# ─── Auth ─────────────────────────────────────────────────────────

def _require_admin():
    """Require an active database-backed administrator identity."""
    from app.utils.auth_helpers import current_auth_user
    user = current_auth_user()
    return bool(user and user.role == 'admin')


# ─── Health check ─────────────────────────────────────────────────

@admin_publish_bp.route('/admin/publish/health', methods=['GET'])
def health():
    """Returns the editor's connection state so admins can verify
    everything is wired before they try to edit + publish."""
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)

    out = {
        'ok': True,
        'auth':   {'ok': True, 'method': 'role'},
        'github': {'ok': False},
        'groq':   {'ok': False},
    }

    # GitHub
    token = current_app.config.get('GITHUB_TOKEN')
    if not current_app.config.get('GITHUB_PUBLISH_ENABLED',False):
        out['github']={'ok':False,'disabled':True,'error':'Repository publishing is disabled for review. No production GitHub write credential is required.'}
    elif not token:
        out['github'] = {
            'ok': False,
            'error': 'GITHUB_TOKEN env var is not set on the server. '
                     'Without this, publish + load both fail. Generate a '
                     'fine-grained review-only PAT only after separate owner approval. '
                     'Do not provide production repository credentials.',
        }
    else:
        try:
            info = gh.repo_info()
            out['github'] = {'ok': True, **info}
        except gh.GitHubPublishError as e:
            out['github'] = {
                'ok': False,
                'status': e.status,
                'error': str(e),
                'hint': ('Check the PAT scope (Contents:read+write) and '
                         'that GITHUB_OWNER / GITHUB_REPO / GITHUB_BRANCH '
                         'env vars match the actual repo.'),
            }

    # Groq
    groq_key = current_app.config.get('GROQ_API_KEY') or os.environ.get('GROQ_API_KEY')
    if groq_key:
        out['groq'] = {
            'ok': True,
            'model': current_app.config.get('GROQ_MODEL') or 'llama-3.3-70b-versatile',
        }
    else:
        out['groq'] = {
            'ok': False,
            'error': 'GROQ_API_KEY not set — AI section generation disabled.',
        }

    # Overall ok if all sub-systems ok
    out['ok'] = out['github']['ok'] and out['groq']['ok']
    return jsonify(out), 200


# ─── GitHub publish ───────────────────────────────────────────────

@admin_publish_bp.route('/admin/publish/file', methods=['GET'])
def get_file():
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)
    path = (request.args.get('path') or '').strip()
    if not path or '..' in path or path.startswith('/'):
        return error_response('INVALID_PATH', 400)
    try:
        content, sha = gh.get_file(path)
        if content is None:
            return error_response('NOT_FOUND', 404, {'detail': f'{path} not in repo'})
        return jsonify({'ok': True, 'path': path, 'content': content, 'sha': sha}), 200
    except gh.GitHubPublishError as e:
        return error_response('GITHUB_ERROR', 502, {'detail': str(e), 'status': e.status})


@admin_publish_bp.route('/admin/publish/pages', methods=['GET'])
def list_pages():
    """List files under a repo directory (default: 'pages').

    Used by the Site Nav Manager (/pages/admin-nav.html) to surface
    admin-created pages that aren't in the nav yet, so admins can
    promote them to the main menu with one click. Caller can pass
    ?dir=pages or any sub-path; we still block traversal.
    """
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)
    dir_arg = (request.args.get('dir') or 'pages').strip()
    if '..' in dir_arg or dir_arg.startswith('/'):
        return error_response('INVALID_PATH', 400)
    try:
        entries = gh.list_directory(dir_arg)
        # Return the same shape the frontend expects; preserve 'path'
        # so the client can build site-rooted URLs unambiguously.
        return jsonify({'ok': True, 'dir': dir_arg, 'pages': entries}), 200
    except gh.GitHubPublishError as e:
        return error_response('GITHUB_ERROR', 502, {'detail': str(e), 'status': e.status})


@admin_publish_bp.route('/admin/publish/upload', methods=['POST'])
def upload_binary():
    """Commit a binary file (image / PDF / etc) to the repo.

    Body (JSON): {
      path:    'images/uploads/<filename>'   (must NOT contain ..)
      content_b64: base64-encoded file bytes
      message: optional commit message
    }

    Size cap: 5 MB. Path must live under images/ (the editor's
    page list doesn't surface other binary targets).
    """
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)

    data = request.get_json(silent=True) or {}
    path = (data.get('path') or '').strip()
    content_b64 = data.get('content_b64')
    message = (data.get('message') or '').strip() or f'Upload {path} via Live Theme Editor'

    if not path or '..' in path or path.startswith('/'):
        return error_response('INVALID_PATH', 400)
    if not path.startswith('images/') and not path.startswith('assets/images/'):
        return error_response('PATH_NOT_ALLOWED', 400, {
            'detail': 'Uploads must go to images/ or assets/images/'
        })
    if not isinstance(content_b64, str):
        return error_response('INVALID_CONTENT', 400)

    import base64 as _b64
    try:
        raw = _b64.b64decode(content_b64, validate=True)
    except Exception:
        return error_response('INVALID_BASE64', 400)
    if len(raw) > 5_000_000:
        return error_response('TOO_LARGE', 400, {'detail': 'Max 5 MB per upload.'})

    # Commit binary via Git Data API (handles arbitrary bytes via
    # base64) rather than Contents API (UTF-8 only).
    try:
        result = gh.commit_multiple_files(
            files=[{'path': path, 'content': raw, 'binary': True}],
            message=message,
            committer_name='PNEC Live Editor',
            committer_email='contact@example.test',
        )
        try:
            current_app.logger.info(
                f'admin.upload ok path={path} bytes={len(raw)} sha={result.get("commit_sha")}'
            )
        except Exception:
            pass
        return jsonify({'ok': True, **result}), 200
    except gh.GitHubPublishError as e:
        return error_response('GITHUB_ERROR', 502, {'detail': str(e), 'status': e.status})


@admin_publish_bp.route('/admin/publish/file', methods=['POST'])
def publish_one_file():
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)

    data = request.get_json(silent=True) or {}
    path = (data.get('path') or '').strip()
    content = data.get('content')
    message = (data.get('message') or '').strip() or 'Edit via PNEC Live Theme Editor'
    expected_sha = (data.get('expected_sha') or '').strip() or None

    if not path or '..' in path or path.startswith('/'):
        return error_response('INVALID_PATH', 400)
    if not isinstance(content, str):
        return error_response('INVALID_CONTENT', 400)
    if len(content) > 5_000_000:
        return error_response('CONTENT_TOO_LARGE', 400, {'detail': 'Max 5 MB per file.'})

    try:
        result = gh.commit_single_file(
            path=path, new_content=content,
            message=message,
            committer_name='PNEC Live Editor',
            committer_email='contact@example.test',
            expected_sha=expected_sha,
        )
        try:
            current_app.logger.info(
                f'admin.publish.file ok path={path} sha={result.get("commit_sha")}'
            )
        except Exception:
            pass
        return jsonify({'ok': True, **result}), 200
    except gh.GitHubPublishError as e:
        # 409 is "someone else committed; reload and merge" — surface
        # the specific code so the editor can show a useful error
        # rather than a generic 502.
        if e.status == 409:
            return error_response('CONFLICT', 409, {'detail': str(e), 'body': e.body})
        return error_response('GITHUB_ERROR', 502, {'detail': str(e), 'status': e.status})


@admin_publish_bp.route('/admin/publish/files', methods=['POST'])
def publish_many_files():
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)

    data = request.get_json(silent=True) or {}
    files = data.get('files') or []
    message = (data.get('message') or '').strip() or 'Batch edit via PNEC Live Theme Editor'

    if not isinstance(files, list) or not files:
        return error_response('NO_FILES', 400, {'detail': 'Provide files: [{path, content}, ...]'})
    if len(files) > 30:
        return error_response('TOO_MANY_FILES', 400, {'detail': 'Max 30 files per commit.'})

    cleaned = []
    for f in files:
        if not isinstance(f, dict):
            return error_response('INVALID_FILE_ENTRY', 400)
        path = (f.get('path') or '').strip()
        content = f.get('content')
        if not path or '..' in path or path.startswith('/'):
            return error_response('INVALID_PATH', 400, {'detail': f'Bad path: {path}'})
        if not isinstance(content, str):
            return error_response('INVALID_CONTENT', 400, {'detail': f'Bad content for {path}'})
        if len(content) > 5_000_000:
            return error_response('CONTENT_TOO_LARGE', 400, {'detail': f'{path} > 5 MB'})
        cleaned.append({'path': path, 'content': content})

    try:
        result = gh.commit_multiple_files(
            files=cleaned, message=message,
            committer_name='PNEC Live Editor',
            committer_email='contact@example.test',
        )
        try:
            current_app.logger.info(
                f'admin.publish.files ok count={result.get("count")} sha={result.get("commit_sha")}'
            )
        except Exception:
            pass
        return jsonify({'ok': True, **result}), 200
    except gh.GitHubPublishError as e:
        return error_response('GITHUB_ERROR', 502, {'detail': str(e), 'status': e.status})


@admin_publish_bp.route('/admin/publish/diff', methods=['POST'])
def diff_file():
    """Server-side unified diff between current file content on the
    configured branch and the proposed new content. Returns:
      { ok, path, current_sha, diff (unified), lines_added, lines_removed }
    """
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)

    data = request.get_json(silent=True) or {}
    path = (data.get('path') or '').strip()
    proposed = data.get('content')
    if not path or '..' in path or path.startswith('/'):
        return error_response('INVALID_PATH', 400)
    if not isinstance(proposed, str):
        return error_response('INVALID_CONTENT', 400)

    try:
        current, sha = gh.get_file(path)
        if current is None:
            current = ''     # new file
            sha = None
    except gh.GitHubPublishError as e:
        return error_response('GITHUB_ERROR', 502, {'detail': str(e), 'status': e.status})

    a = current.splitlines(keepends=True)
    b = proposed.splitlines(keepends=True)
    udiff = ''.join(difflib.unified_diff(
        a, b, fromfile=f'{path} (HEAD)', tofile=f'{path} (proposed)',
        lineterm='',
    ))
    added = sum(1 for line in udiff.split('\n')
                if line.startswith('+') and not line.startswith('+++'))
    removed = sum(1 for line in udiff.split('\n')
                  if line.startswith('-') and not line.startswith('---'))
    return jsonify({
        'ok':            True,
        'path':          path,
        'current_sha':   sha,
        'diff':          udiff,
        'lines_added':   added,
        'lines_removed': removed,
        'identical':     (current == proposed),
        'new_file':      (sha is None),
    }), 200


@admin_publish_bp.route('/admin/publish/history', methods=['GET'])
def file_history():
    """Recent commits touching the given file."""
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)
    path = (request.args.get('path') or '').strip()
    if not path:
        return error_response('INVALID_PATH', 400)
    try:
        items = gh.file_history(path, per_page=int(request.args.get('per_page', 10)))
        return jsonify({'ok': True, 'path': path, 'items': items}), 200
    except gh.GitHubPublishError as e:
        return error_response('GITHUB_ERROR', 502, {'detail': str(e), 'status': e.status})


@admin_publish_bp.route('/admin/publish/file-at', methods=['GET'])
def file_at():
    """Fetch a file's content at a specific commit SHA. Powers
    the editor's 'preview before rollback' feature — admin clicks
    a commit in the history list, sees what the file looked like
    then, decides whether to restore."""
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)
    path = (request.args.get('path') or '').strip()
    ref  = (request.args.get('ref')  or '').strip()
    if not path or '..' in path or path.startswith('/'):
        return error_response('INVALID_PATH', 400)
    if not ref:
        return error_response('INVALID_REF', 400)
    try:
        content, sha = gh.get_file_at(path, ref)
        if content is None:
            return error_response('NOT_FOUND_AT_REF', 404,
                                  {'detail': f'{path} not present at {ref[:7]}'})
        return jsonify({'ok': True, 'path': path, 'ref': ref, 'sha': sha, 'content': content}), 200
    except gh.GitHubPublishError as e:
        return error_response('GITHUB_ERROR', 502, {'detail': str(e), 'status': e.status})


@admin_publish_bp.route('/admin/publish/rollback', methods=['POST'])
def rollback_file():
    """Restore a file to its state at a specific commit SHA. Creates a
    new commit on the branch — does NOT rewrite history.

    Body: { path, sha, message? }
    """
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)
    data = request.get_json(silent=True) or {}
    path = (data.get('path') or '').strip()
    sha  = (data.get('sha')  or '').strip()
    message = (data.get('message') or '').strip() or f'Rollback {path} to {sha[:7]}'
    if not path or not sha:
        return error_response('INVALID_INPUT', 400)
    try:
        old_content, _old_sha = gh.get_file_at(path, sha)
        if old_content is None:
            return error_response('NOT_FOUND_AT_SHA', 404,
                                  {'detail': f'{path} not present at commit {sha[:7]}'})
        result = gh.commit_single_file(
            path=path, new_content=old_content, message=message,
            committer_name='PNEC Live Editor (rollback)',
            committer_email='contact@example.test',
        )
        return jsonify({'ok': True, **result}), 200
    except gh.GitHubPublishError as e:
        return error_response('GITHUB_ERROR', 502, {'detail': str(e), 'status': e.status})


@admin_publish_bp.route('/admin/publish/status', methods=['GET'])
def workflow_status():
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)
    runs = gh.workflow_runs(per_page=int(request.args.get('per_page', 5)))
    items = []
    for r in runs:
        items.append({
            'id':           r.get('id'),
            'name':         r.get('name'),
            'status':       r.get('status'),        # queued/in_progress/completed
            'conclusion':   r.get('conclusion'),    # success/failure/cancelled/null
            'head_commit':  (r.get('head_commit') or {}).get('message'),
            'head_sha':     (r.get('head_commit') or {}).get('id'),
            'html_url':     r.get('html_url'),
            'created_at':   r.get('created_at'),
            'updated_at':   r.get('updated_at'),
        })
    return jsonify({'ok': True, 'items': items}), 200


# ─── Groq AI section generation ───────────────────────────────────

import requests as _requests


@admin_publish_bp.route('/admin/ai/section', methods=['POST'])
def ai_section():
    """Generate page-section HTML via Groq.

    Body: {
      prompt:        "Plain-English description of what the section should say"
      section_kind:  "hero" | "card_list" | "image_with_text" | "cta" | "faq" | "text"
      tone:          "neighborly" (default) | "urgent" | "formal"
      page_context:  optional short note about the page the section will live on
    }

    Returns: { html, model, usage }
    """
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)

    data = request.get_json(silent=True) or {}
    user_prompt   = (data.get('prompt') or '').strip()
    section_kind  = (data.get('section_kind') or 'text').strip()
    tone          = (data.get('tone') or 'neighborly').strip()
    page_context  = (data.get('page_context') or '').strip()

    if not user_prompt or len(user_prompt) > 4000:
        return error_response('INVALID_PROMPT', 400)

    api_key = current_app.config.get('GROQ_API_KEY') or os.environ.get('GROQ_API_KEY')
    if not api_key:
        return error_response('GROQ_NOT_CONFIGURED', 503,
                              {'detail': 'GROQ_API_KEY env var is required.'})

    model = current_app.config.get('GROQ_MODEL') or 'llama-3.3-70b-versatile'
    url = (current_app.config.get('GROQ_API_URL') or 'https://api.groq.com/openai/v1').rstrip('/') + '/chat/completions'

    system = (
        "You write semantic HTML section blocks for the Poway Neighborhood "
        "Emergency Corps (PNEC) website. Output ONLY the HTML — no markdown "
        "fences, no preamble, no closing remarks. Use existing brand classes "
        "where helpful (cream + forest theme). Heading levels start at h2. "
        "Tone: " + tone + ". Section kind: " + section_kind + ". "
        + (("Page context: " + page_context + ". ") if page_context else "")
        + "Never invent statistics, addresses, or volunteer names. Real "
        "phone numbers PNEC publishes: contact@example.test (general), "
        "858-668-1250 (homebound helpline), 2-1-1 (financial aid). "
        "Real upcoming event: 12th Annual Emergency & Safety Fair, "
        "May 23 2026, Old Poway Park, 9 AM-1 PM. Keep responses concise "
        "and actionable — Poway residents are reading these to make decisions."
    )

    try:
        resp = _requests.post(url, timeout=30, headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }, json={
            'model': model,
            'temperature': 0.5,
            'max_tokens': 1200,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user',   'content': user_prompt},
            ],
        })
        if resp.status_code == 401:
            return error_response('GROQ_AUTH', 502, {
                'detail': 'GROQ_API_KEY rejected by Groq — check the key is valid and not revoked.',
            })
        if resp.status_code == 429:
            return error_response('GROQ_RATE_LIMITED', 502, {
                'detail': 'Groq rate-limit hit. Wait a minute and try again.',
            })
        if not resp.ok:
            return error_response('GROQ_API_ERROR', 502, {
                'detail': f'Groq returned {resp.status_code}',
                'body': resp.text[:400],
            })

        # Be paranoid about response shape — handle every layer that
        # could be malformed: not-JSON, missing choices, missing
        # message, non-string content.
        try:
            body = resp.json()
        except Exception:
            return error_response('GROQ_BAD_JSON', 502, {
                'detail': 'Groq returned non-JSON output.',
                'body': (resp.text or '')[:400],
            })
        if not isinstance(body, dict):
            return error_response('GROQ_BAD_SHAPE', 502, {'detail': 'Response not a dict.'})
        choices = body.get('choices')
        if not isinstance(choices, list) or not choices:
            return error_response('GROQ_NO_CHOICES', 502, {'detail': 'No choices in response.'})
        msg = (choices[0] or {}).get('message') or {}
        html = msg.get('content')
        if not isinstance(html, str):
            return error_response('GROQ_NO_CONTENT', 502, {
                'detail': 'Empty / non-string message content.',
            })

        # Strip accidental markdown fences ```html … ```
        html = html.strip()
        if html.startswith('```'):
            # Drop the opening fence (and any language tag) up to the
            # first newline, then the trailing ``` if present.
            nl = html.find('\n')
            html = html[nl + 1:] if nl >= 0 else ''
            if html.rstrip().endswith('```'):
                html = html.rstrip()[:-3].rstrip()

        # Length sanity
        if len(html) > 50_000:
            html = html[:50_000] + '\n<!-- truncated to 50KB -->'

        return jsonify({
            'ok':    True,
            'html':  html,
            'model': body.get('model') or model,
            'usage': body.get('usage') or {},
        }), 200
    except _requests.exceptions.Timeout:
        return error_response('GROQ_TIMEOUT', 504, {'detail': 'Groq did not respond within 30s.'})
    except _requests.exceptions.ConnectionError:
        return error_response('GROQ_NETWORK', 502, {'detail': 'Could not reach Groq.'})
    except Exception as e:
        try:
            current_app.logger.exception('admin.ai_section failed')
        except Exception:
            pass
        return error_response('AI_ERROR', 502, {'detail': str(e)[:200]})


# ────────────────────────────────────────────────────────────────────
# AI Prompt Engineer (v3.29, 2026-05-13)
# ────────────────────────────────────────────────────────────────────
# The previous /admin/ai/section endpoint asked Groq to generate page
# HTML directly. That capped creativity at Groq's ceiling. The new
# pattern uses Groq as a META-prompt-engineer: it reads the actual
# page content + the user's plain-English change request, and emits
# a tailored prompt the user pastes into a MORE capable AI (Claude,
# Gemini, or ChatGPT). The user runs that AI, copies its modified
# HTML back into the editor, previews, saves.
#
# Why this is better:
#   - PNEC admins get to use the strongest available model for each
#     edit (Claude is dramatically better than Llama-3.3 at producing
#     correct, semantically-clean HTML inside a complex existing page)
#   - The engineered prompt embeds the entire current HTML inline, so
#     the user only copies-pastes ONCE per edit
#   - Each AI has different prompt-style preferences. Groq tailors the
#     output to the chosen target.

# Tailored format hints per target AI. These are appended to Groq's
# system prompt so the generated prompt fits the target AI's strengths.
_TARGET_AI_PROFILES = {
    'claude': {
        'label':       'Claude (Anthropic)',
        'url':         'https://claude.ai',
        'format_hints': (
            'Use XML tags to structure the prompt: <current_html>, '
            '<change_request>, <constraints>, <output_format>. State '
            'constraints as a bulleted list. Ask Claude to think step-by-'
            'step inside a <thinking> tag before producing output. '
            'Place the response inside a single <output> tag and demand '
            'this EXACTLY in the <output_format> section: '
            '"Inside <output> you MUST emit the COMPLETE rewritten HTML '
            'document, byte-for-byte ready to paste-replace the original '
            'file. Start with the very first character (e.g. <!DOCTYPE '
            'html>) and end with </html>. Reproduce every unchanged byte '
            'verbatim — every line of <style>, <script>, <link>, '
            'comments, whitespace, attributes, IDs, classes, the lot — '
            'and only the requested change should differ. Do NOT '
            'summarize, abbreviate, ellipsize (no \'...\', no \'/* '
            'unchanged */\'), describe changes, output a diff/patch, '
            'or say things like \'replace X with Y\'. Do NOT add any '
            'prose before or after the <output> tag. The admin will '
            'overwrite the source file with the contents of <output> '
            'directly — anything else breaks the workflow."'
        ),
    },
    'gemini': {
        'label':       'Gemini (Google)',
        'url':         'https://gemini.google.com',
        'format_hints': (
            'Be concise and direct. Lead with the role + task in one '
            'sentence. Use one markdown heading each for the task, the '
            'HTML, and the constraints. Wrap the existing HTML in a '
            '```html fenced block. End with an "### Output format" '
            'section that says EXACTLY: '
            '"Respond with one and only one ```html fenced block '
            'containing the COMPLETE rewritten HTML document, ready to '
            'paste-replace the original file. Start with the very first '
            'character (e.g. <!DOCTYPE html>) and end with </html>. '
            'Reproduce every unchanged byte verbatim — every line of '
            '<style>, <script>, <link>, comments, whitespace, '
            'attributes, IDs, classes, the lot — and only the requested '
            'change should differ. Do NOT summarize, abbreviate, '
            'ellipsize (no \'...\', no \'/* unchanged */\'), describe '
            'changes, output a diff/patch, or say things like \'replace '
            'X with Y\'. Do NOT add any text before or after the '
            '```html block. The admin will copy the contents of the '
            'block directly into a code editor."'
        ),
    },
    'chatgpt': {
        'label':       'ChatGPT (OpenAI)',
        'url':         'https://chatgpt.com',
        'format_hints': (
            'Open with a clear ROLE statement ("You are a senior web '
            'developer..."). Structure the body as numbered TASK steps. '
            'End with an OUTPUT FORMAT block that says EXACTLY: '
            '"Return ONLY the COMPLETE rewritten HTML document as raw '
            'text, with NO markdown code fences, NO commentary, NO '
            'preamble, NO trailing notes. Start your reply with the '
            'very first character of the document (e.g. <!DOCTYPE '
            'html>) and end with </html>. Reproduce every unchanged '
            'byte verbatim — every line of <style>, <script>, <link>, '
            'comments, whitespace, attributes, IDs, classes, the lot — '
            'and only the requested change should differ. Do NOT '
            'summarize, abbreviate, ellipsize (no \'...\', no \'/* '
            'unchanged */\'), describe changes, output a diff/patch, '
            'or say things like \'replace X with Y\'. The admin will '
            'paste your entire reply into a code editor as the new '
            'file content — anything else breaks the workflow." Place '
            'the existing HTML inside a ```html code fence for clarity '
            'in the prompt itself (NOT for the AI\'s response).'
        ),
    },
}


def _build_steps(target_label, target_url):
    """Step-by-step instructions shown beside the engineered prompt.

    Worded generically (no target-name repetition) so the same steps
    read sensibly even when the admin changes the target AI radio
    after the prompt has been generated. The "Copy & open <target>"
    button + the result-title carry the target-specific info.
    """
    return [
        'Open the AI in a new tab — use the "Copy & open" button above to copy the prompt and open the AI in one click.',
        'Paste the prompt into the AI. It already contains the current page HTML, so one paste does it.',
        'Wait for the AI to return the modified HTML, then copy its full response (just the HTML, no extra commentary).',
        'Use the "Step 2 · Paste the AI\'s response & apply" panel below to paste it back, preview it inline, and apply to the editor.',
        'Once the editor source is replaced, click "Publish to GitHub →" to commit. The live site rebuilds automatically.',
    ]


# A literal placeholder Groq inserts into the engineered prompt; the
# backend swaps this for the full page HTML before returning to the
# user. This lets us send Groq a SUMMARY (no inline <style>/<script>)
# while still embedding the FULL HTML in the engineered prompt the
# user pastes into the target AI — which is what keeps us under
# Groq's 12000 TPM free-tier limit on long pages.
#
# We deliberately use an alphanumeric+underscore token (no <, >, /)
# because Groq has a tendency to mangle angle-bracket delimiters when
# the surrounding context is HTML/XML. A pure underscore-delimited
# token survives faithfully in every output we've tested.
PAGE_HTML_PLACEHOLDER = '__PNEC_FULL_PAGE_HTML__'

# Near-miss placeholders Groq sometimes emits — we accept any of these
# as a successful placeholder match (fall back in priority order). This
# avoids the "append at end" fallback in 99% of real-world generations.
_PLACEHOLDER_ALIASES = (
    '__PNEC_FULL_PAGE_HTML__',
    '<__PNEC_FULL_PAGE_HTML__>',
    '{PNEC_FULL_PAGE_HTML}',
    '{{PNEC_FULL_PAGE_HTML}}',
    '<<<<PNEC_FULL_PAGE_HTML>>>>',
    '<<<<FULL_PAGE_HTML>>>>',     # legacy spelling
    '<<<FULL_PAGE_HTML>>>',
    '<<FULL_PAGE_HTML>>',
    '<FULL_PAGE_HTML>',
    '[FULL_PAGE_HTML]',
    '{FULL_PAGE_HTML}',
    '{{FULL_PAGE_HTML}}',
)


# ── Page summariser for Groq ─────────────────────────────────────────
# Strips inline <style>, <script>, <link>, and noisy inline style="..."
# attributes from the page HTML before sending it to Groq. The target
# AI receives the FULL untrimmed HTML in the engineered prompt — Groq
# just needs to see the page STRUCTURE (h1/h2/section landmarks) so it
# can write a prompt that references the right anchors.
import re as _re

def _summarize_html_for_groq(html_text, max_bytes=18_000):
    """Return a (summary_text, was_trimmed) tuple.

    The summary preserves the structural skeleton of the page so Groq
    can reference real landmarks in the engineered prompt, while
    stripping the large inline assets that bloat the token count.
    """
    summary = html_text

    # 1. Strip <style>...</style> blocks (these can be ~20 KB each on
    #    PNEC's admin-editor.html). Replace with a placeholder so Groq
    #    knows there was a stylesheet there.
    summary = _re.sub(
        r'<style[^>]*>.*?</style>',
        '<style>/* … style block omitted from summary … */</style>',
        summary, flags=_re.DOTALL | _re.IGNORECASE,
    )

    # 2. Strip <script>...</script> blocks similarly.
    summary = _re.sub(
        r'<script[^>]*>.*?</script>',
        '<script>/* … script block omitted from summary … */</script>',
        summary, flags=_re.DOTALL | _re.IGNORECASE,
    )

    # 3. Drop self-closing <link> / <meta> head tags that don't affect
    #    the visible content the AI is editing.
    summary = _re.sub(r'<link\b[^>]*>', '', summary, flags=_re.IGNORECASE)

    # 4. Collapse long inline style="..." attributes to keep tag opening
    #    tags short. We keep the existence of the attribute so Groq
    #    can tell the target AI to preserve inline styling, but we
    #    don't ship every rgba() declaration.
    summary = _re.sub(
        r'style="[^"]{120,}"',
        'style="…"',
        summary,
    )

    # 5. Collapse runs of blank lines.
    summary = _re.sub(r'\n{3,}', '\n\n', summary)

    # 6. Truncate to budget. Most PNEC pages summarise to < 15 KB; the
    #    admin-editor.html test case goes from ~150 KB → ~10 KB.
    was_trimmed = False
    if len(summary) > max_bytes:
        summary = summary[:max_bytes] + '\n<!-- truncated for AI summary; the target AI will see the full untruncated page -->'
        was_trimmed = True

    return summary, was_trimmed


@admin_publish_bp.route('/admin/ai/prompt-engineer', methods=['POST'])
def ai_prompt_engineer():
    """Meta-prompt-engineer: use Groq to generate a prompt the user can
    paste into Claude / Gemini / ChatGPT to make a specific change to a
    specific page on this site.

    Body:
      path:        repo-relative path to the page (required)
      description: plain-English description of the desired change (required)
      target_ai:   'claude' | 'gemini' | 'chatgpt'  (default: 'claude')

    Returns:
      {
        ok: true,
        prompt:          <engineered prompt to paste into target AI>,
        target_ai:       <key>,
        target_ai_label: <human-readable label>,
        target_ai_url:   <where to open the AI>,
        page_path:       <echoed back>,
        page_bytes:      <size of the embedded HTML>,
        steps:           [<copy-paste instructions>],
        model:           <Groq model used>,
        usage:           <Groq token accounting>,
      }
    """
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)

    data = request.get_json(silent=True) or {}
    # Use the module-level `_as_str` helper — coerces non-string inputs
    # (e.g. a dict from a click-event serialization bug) to '' / default
    # so we return INVALID_PATH / INVALID_DESCRIPTION 400 instead of a 500.
    page_path   = _as_str(data.get('path'))
    description = _as_str(data.get('description'))
    target_ai   = _as_str(data.get('target_ai'), 'claude').lower()

    # ── Validation ───────────────────────────────────────────────
    if not page_path or '..' in page_path or page_path.startswith('/'):
        return error_response('INVALID_PATH', 400,
                              {'detail': 'path must be a repo-relative file path.'})
    if not description:
        return error_response('INVALID_DESCRIPTION', 400,
                              {'detail': 'description is required.'})
    if len(description) > 4000:
        return error_response('INVALID_DESCRIPTION', 400,
                              {'detail': 'description must be ≤ 4000 chars.'})
    profile = _TARGET_AI_PROFILES.get(target_ai)
    if profile is None:
        return error_response('INVALID_TARGET_AI', 400,
                              {'detail': 'target_ai must be claude, gemini, or chatgpt.'})

    api_key = current_app.config.get('GROQ_API_KEY') or os.environ.get('GROQ_API_KEY')
    if not api_key:
        return error_response('GROQ_NOT_CONFIGURED', 503,
                              {'detail': 'GROQ_API_KEY env var is required.'})

    # ── Pull the current page content from GitHub ────────────────
    try:
        page_content, page_sha = gh.get_file(page_path)
        if page_content is None:
            return error_response('PAGE_NOT_FOUND', 404,
                                  {'detail': f'{page_path} is not in the repo.'})
    except gh.GitHubPublishError as e:
        return error_response('GITHUB_ERROR', 502,
                              {'detail': str(e), 'status': e.status})

    # Total bytes (used in the response so the UI can show "X KB embedded")
    page_bytes = len(page_content)

    # Build a SUMMARISED view of the page for Groq (strips inline
    # <style>/<script>/<link>, collapses long inline style="..." attrs,
    # caps at ~18 KB). This keeps us under Groq's 12000 TPM free-tier
    # limit even for the admin-editor page (which is ~150 KB raw).
    summary_html, was_summary_trimmed = _summarize_html_for_groq(page_content)

    # ── Build the meta-prompt for Groq ───────────────────────────
    model = current_app.config.get('GROQ_MODEL') or 'llama-3.3-70b-versatile'
    url = (current_app.config.get('GROQ_API_URL') or 'https://api.groq.com/openai/v1').rstrip('/') + '/chat/completions'

    # The engineered prompt Groq emits will contain the literal token
    # `{ph}` exactly once — the backend substitutes it for the full
    # untrimmed page HTML before returning the prompt to the user.
    ph = PAGE_HTML_PLACEHOLDER

    system_prompt = (
        'You are a senior prompt engineer specializing in generating high-quality '
        'one-shot prompts for large language models. Your job is to write a prompt '
        f'that the user can paste DIRECTLY into {profile["label"]}, along with no other '
        'context, that will instruct it to modify an HTML page from the Poway Neighborhood '
        'Emergency Corps (PNEC) website according to the user\'s description.\n\n'
        f'TARGET AI: {profile["label"]}\n'
        f'TARGET AI FORMAT GUIDANCE: {profile["format_hints"]}\n\n'
        'YOUR OUTPUT MUST:\n'
        '1. Be a single self-contained prompt — no preamble like "Here is the prompt:".\n'
        f'2. Include the literal string {ph} EXACTLY ONCE inside the prompt, in the place where the target AI should receive the current HTML document. Our backend will substitute this token for the FULL untrimmed page HTML before delivering the prompt to the user. Do not paste the HTML you see below into the prompt — use {ph} instead.\n'
        '3. Explicitly state PNEC brand constraints: forest green (#0e3b21), cream backgrounds (#fbf8f1), DM Sans typography, no emojis as icons, neighborly tone, never alarmist, accessible markup (h1/h2/h3 hierarchy, alt text, ARIA where needed).\n'
        '4. ABSOLUTELY CRITICAL — paste-replace workflow. Tell the target AI, in unambiguous language, that its reply must be the COMPLETE rewritten HTML document, byte-for-byte ready to paste-replace the original file. The first character of its reply must be the first character of the document (e.g. "<!DOCTYPE html>") and the last must be "</html>". It must reproduce every unchanged byte verbatim — every <style>, <script>, <link>, comment, whitespace, attribute, id, class — and only the requested change should differ. EXPLICITLY FORBID: diffs, patches, "replace X with Y" instructions, partial snippets, ellipses ("..."), placeholder comments ("/* unchanged */", "// rest of file"), summaries, descriptions of changes, prose before or after the code, multiple alternative versions. Use the exact wording from the TARGET AI FORMAT GUIDANCE above for the output-format block.\n'
        '5. Be specific about WHERE in the existing HTML the change should land (reference visible markers like h2 text, section IDs, or content anchors from the document summary below) — but the AI must STILL output the entire file, not just that region.\n'
        '6. Tell the target AI to preserve all unchanged content verbatim — including the inline <style> and <script> blocks (you only see placeholders for those in the summary, but the full page will be substituted in via the token). Reinforce that even very large pages must be returned in full.\n'
        '7. Never invent PNEC facts. Real values it can reference: contact@example.test, 858-668-1250 homebound helpline, 2-1-1 financial aid, 12th Annual Emergency & Safety Fair on May 23 2026 at Old Poway Park 9 AM–1 PM.\n'
        '8. Add one sentence near the top of the engineered prompt that frames the workflow for the target AI: "Your response will be programmatically copy-pasted into a code editor as the new file — anything that isn\'t the new file content breaks the workflow."\n\n'
        'Do not say anything other than the prompt itself. The very first character of your '
        'response must be the first character of the prompt the user will paste.'
    )

    summary_note = (
        '(Note: the inline <style>, <script>, and <link> elements have been '
        'replaced with placeholders to keep this summary short. The target '
        'AI will receive the FULL untrimmed page via the substitution token; '
        'tell it to preserve those omitted blocks verbatim.)'
        if not was_summary_trimmed else
        '(Note: the page is large enough that this summary was further '
        'truncated. The target AI will still receive the FULL untrimmed '
        f'page via the {ph} token — tell it to preserve everything not '
        'explicitly being changed.)'
    )

    user_payload = (
        f'PAGE PATH: {page_path}\n'
        f'PAGE SIZE: {page_bytes} bytes total\n\n'
        f'USER\'S DESCRIPTION OF DESIRED CHANGE:\n'
        f'"""\n{description}\n"""\n\n'
        f'STRUCTURAL SUMMARY OF THE PAGE TO EDIT  {summary_note}\n'
        f'"""\n{summary_html}\n"""\n\n'
        f'Generate the prompt now. Remember: use the literal token {ph} '
        f'where the full HTML should appear — do not embed the summary above.'
    )

    try:
        resp = _requests.post(url, timeout=45, headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }, json={
            'model':       model,
            'temperature': 0.4,
            'max_tokens':  4000,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user',   'content': user_payload},
            ],
        })
        if resp.status_code == 401:
            return error_response('GROQ_AUTH', 502, {
                'detail': 'GROQ_API_KEY rejected by Groq — check the key is valid and not revoked.',
            })
        if resp.status_code == 429:
            return error_response('GROQ_RATE_LIMITED', 502, {
                'detail': 'Groq rate-limit hit. Wait a minute and try again.',
            })
        if not resp.ok:
            return error_response('GROQ_API_ERROR', 502, {
                'detail': f'Groq returned {resp.status_code}',
                'body':   (resp.text or '')[:400],
            })

        try:
            body = resp.json()
        except Exception:
            return error_response('GROQ_BAD_JSON', 502,
                                  {'detail': 'Groq returned non-JSON.', 'body': (resp.text or '')[:400]})
        if not isinstance(body, dict):
            return error_response('GROQ_BAD_SHAPE', 502, {'detail': 'Response not a dict.'})
        choices = body.get('choices')
        if not isinstance(choices, list) or not choices:
            return error_response('GROQ_NO_CHOICES', 502, {'detail': 'No choices in response.'})
        msg = (choices[0] or {}).get('message') or {}
        engineered_prompt = msg.get('content')
        if not isinstance(engineered_prompt, str) or not engineered_prompt.strip():
            return error_response('GROQ_NO_CONTENT', 502, {'detail': 'Empty content from Groq.'})

        engineered_prompt = engineered_prompt.strip()

        # ── Substitute the placeholder with the FULL untrimmed HTML ──
        # LLMs are imperfect — Groq sometimes mangles the placeholder
        # token (e.g. emits `>>>>FULL_PAGE_HTML>>>>` instead of
        # `<<<<FULL_PAGE_HTML>>>>` when the surrounding context is HTML
        # tags). We accept several near-miss aliases. Strategy:
        #   1. Walk the alias list; the first one that appears is the
        #      "canonical" placeholder Groq actually used.
        #   2. Replace the first occurrence with the full HTML.
        #   3. Drop any duplicate occurrences of the SAME alias.
        #   4. If no alias matches → append the HTML in a labelled
        #      block (we still want a usable prompt).
        matched_alias = None
        for alias in _PLACEHOLDER_ALIASES:
            if alias in engineered_prompt:
                matched_alias = alias
                break

        if matched_alias is not None:
            count = engineered_prompt.count(matched_alias)
            first_idx = engineered_prompt.find(matched_alias)
            engineered_prompt = (
                engineered_prompt[:first_idx]
                + page_content
                + engineered_prompt[first_idx + len(matched_alias):]
            )
            # Drop duplicates of the same alias
            engineered_prompt = engineered_prompt.replace(matched_alias, '')
            if matched_alias == PAGE_HTML_PLACEHOLDER:
                placeholder_handling = 'substituted' if count == 1 else f'substituted-first-deduped-{count-1}'
            else:
                placeholder_handling = f'substituted-alias({matched_alias})'
        else:
            engineered_prompt = (
                engineered_prompt.rstrip()
                + '\n\n--- CURRENT PAGE HTML (preserve everything you do not change) ---\n\n'
                + page_content
            )
            placeholder_handling = 'appended'

        # Cap the included summary at 4 KB so the response stays small
        # (the user only needs to skim the structure Groq saw, not all
        # 18 KB of it). For larger summaries we send a head + tail
        # snippet so the user can confirm key landmarks are present.
        if len(summary_html) <= 4000:
            summary_preview = summary_html
            summary_preview_truncated = False
        else:
            head_chunk = summary_html[:2400]
            tail_chunk = summary_html[-1200:]
            summary_preview = (
                head_chunk
                + f'\n\n<!-- … (omitted ~{len(summary_html) - 3600} chars from middle of summary) … -->\n\n'
                + tail_chunk
            )
            summary_preview_truncated = True

        return jsonify({
            'ok':                       True,
            'prompt':                   engineered_prompt,
            'target_ai':                target_ai,
            'target_ai_label':          profile['label'],
            'target_ai_url':            profile['url'],
            'page_path':                page_path,
            'page_bytes':               page_bytes,
            'page_sha':                 page_sha,
            'summary_bytes':            len(summary_html),
            'summary_trimmed':          was_summary_trimmed,
            'summary_preview':          summary_preview,
            'summary_preview_truncated': summary_preview_truncated,
            'placeholder_handled':      placeholder_handling,
            'steps':                    _build_steps(profile['label'], profile['url']),
            'model':                    body.get('model') or model,
            'usage':                    body.get('usage') or {},
        }), 200
    except _requests.exceptions.Timeout:
        return error_response('GROQ_TIMEOUT', 504,
                              {'detail': 'Groq did not respond within 45s.'})
    except _requests.exceptions.ConnectionError:
        return error_response('GROQ_NETWORK', 502,
                              {'detail': 'Could not reach Groq.'})
    except Exception as e:
        try:
            current_app.logger.exception('admin.ai_prompt_engineer failed')
        except Exception:
            pass
        return error_response('AI_PROMPT_ENGINEER_ERROR', 502, {'detail': str(e)[:200]})
