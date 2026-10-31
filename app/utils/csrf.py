"""Exact-origin CSRF validation for cookie-authenticated writes, including forms.

Bearer authentication is checked separately and never falls back to cookies.
Clients without Origin must obtain a session-bound token from /api/auth/csrf.
"""
import secrets
from flask import request, session, jsonify, current_app
from flask_login import current_user

APPROVED_ORIGINS = [
    'http://localhost:4000', 'http://127.0.0.1:4000',
    'http://localhost:4600', 'http://127.0.0.1:4600',
    'http://localhost:4500', 'http://127.0.0.1:4500',
    'http://localhost:8080', 'http://127.0.0.1:8080',
    'http://pnec-review.invalid', 'https://pnec-review.invalid',
    'https://open-coding-society.github.io', 'https://whitelunarium.github.io',
    'https://powaynec.com', 'https://www.powaynec.com',
    'https://api.pnec-review.invalid',
]


def install_csrf_protection(app):
    @app.get('/api/auth/csrf')
    def csrf_token():
        session.setdefault('_csrf_token', secrets.token_urlsafe(32))
        response = jsonify({'csrf_token': session['_csrf_token']})
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.before_request
    def protect_cookie_writes():
        if request.method in ('GET', 'HEAD', 'OPTIONS') or not current_app.config['CSRF_PROTECTION_ENABLED']:
            return None
        origin = request.headers.get('Origin')
        # Reject opaque, malformed and unapproved origins, even on login.
        if origin is not None:
            if origin in current_app.config['APPROVED_ORIGINS']:
                return None
            return jsonify({'error': 'CSRF_REJECTED'}), 403
        # Only an explicitly supplied bearer identity is used by the bridge.
        # Invalid bearers are never allowed to use a cookie identity.
        if request.headers.get('Authorization', '').startswith('Bearer '):
            return None
        if current_user.is_authenticated:
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('_csrf_token', '')
            expected = session.get('_csrf_token', '')
            if not expected or not secrets.compare_digest(str(supplied).encode('utf-8'), expected.encode('utf-8')):
                return jsonify({'error': 'CSRF_REJECTED'}), 403
        return None
