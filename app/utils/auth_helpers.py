import re
import time
from flask import request, current_app
from flask_login import current_user


def get_token_user():
    """Return user from Bearer token header, or None."""
    from app.models.user import User
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:].strip()
        if re.fullmatch(r'p1[0-9a-f]{62}', token):
            age = time.time() - int(token[2:10], 16)
            if 0 <= age < current_app.config['BEARER_TOKEN_MAX_AGE']:
                return User.query.filter_by(auth_token=token, is_active=True).first()
    return None


def current_auth_user():
    """Return authenticated user from Bearer token or Flask session."""
    if request.headers.get('Authorization', '').startswith('Bearer '):
        return get_token_user()
    if current_user.is_authenticated:
        return current_user
    return None
