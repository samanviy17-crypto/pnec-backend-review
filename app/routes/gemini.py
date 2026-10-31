# app/routes/gemini.py
#
# PNEC chatbot route. NAMING HISTORY: this file and the URL it exposes
# (/api/gemini) were created when the chatbot used Google Gemini. We
# later switched the primary provider to Groq (Llama-3.3-70B) because
# Groq's free tier handles far more requests per day. The file name
# and URL stayed for backwards compat with the deployed frontend
# (4 call sites in assets/js/).
#
# The actual provider order (Groq primary, Gemini fallback) lives in
# app/services/chat_service.py. Read that file for the why.

import time

from flask import Blueprint, current_app, jsonify, request

from app.services import chat_service
from app.utils.errors import error_response

gemini_bp = Blueprint('gemini', __name__)
_rate_limit_hits = {}
_redis_client = None
_redis_client_url = None


@gemini_bp.route('/gemini', methods=['POST'])
def proxy_gemini():
    """
    Purpose: Generate a free-form chatbot answer through the server-side chat proxy.
    Provider order: Groq primary, Gemini fallback. See chat_service.py for why.
    Expected JSON: { prompt: string, text: string }
    """
    data = request.get_json(silent=True) or {}
    prompt = data.get('prompt', '')
    user_text = data.get('text') or data.get('message') or data.get('question') or ''
    history = data.get('history') or []
    image_data = data.get('image_data')
    image_mime_type = data.get('image_mime_type', 'image/jpeg')

    if _is_rate_limited():
        return error_response('RATE_LIMITED', 429, {'detail': 'Too many chatbot requests. Please wait a minute and try again.'})

    text, err = chat_service.generate_chat_response(prompt, user_text, history, image_data, image_mime_type)
    if err == 'MISSING_MESSAGE':
        return error_response('VALIDATION_FAILED', 400, {'detail': 'Missing chatbot message.'})
    if err == 'GEMINI_NOT_CONFIGURED':
        return error_response('SERVER_ERROR', 503, {'detail': 'No chat provider configured (set GROQ_API_KEY or GEMINI_API_KEY).'})
    if err:
        detail = err.get('detail') if isinstance(err, dict) else 'Chat proxy request failed.'
        return error_response('SERVER_ERROR', 502, {'detail': detail})

    return jsonify({'text': text}), 200


def _is_rate_limited():
    limit = current_app.config.get('GEMINI_RATE_LIMIT_PER_MINUTE', 20)
    if limit <= 0:
        return False

    redis_client = _get_redis_client()
    if redis_client:
        key = _rate_limit_key()
        try:
            count = redis_client.incr(key)
            if count == 1:
                redis_client.expire(key, 60)
            return count > limit
        except Exception:
            pass

    now = time.time()
    window_start = now - 60
    key = _rate_limit_key()

    hits = [timestamp for timestamp in _rate_limit_hits.get(key, []) if timestamp >= window_start]
    if len(hits) >= limit:
        _rate_limit_hits[key] = hits
        return True

    hits.append(now)
    _rate_limit_hits[key] = hits
    return False


def _rate_limit_key():
    client_id = request.headers.get('X-Forwarded-For', request.remote_addr or 'anonymous').split(',')[0].strip()
    return f'gemini-rate-limit:{client_id}'


def _get_redis_client():
    global _redis_client, _redis_client_url

    redis_url = current_app.config.get('REDIS_URL')
    if not redis_url:
        return None

    if _redis_client and _redis_client_url == redis_url:
        return _redis_client

    try:
        import redis
        _redis_client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        _redis_client.ping()
        _redis_client_url = redis_url
        return _redis_client
    except Exception:
        _redis_client = None
        _redis_client_url = None
        return None
