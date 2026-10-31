# app/services/auth_service.py
# Responsibility: Auth business logic — create accounts, validate credentials.
# Routes delegate to these functions; no Flask request objects here.

from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from app.models.user import User, VALID_ROLES
from app.utils.errors import ERROR_MESSAGES


def create_user(email, password, display_name, neighborhood_id=None):
    """
    Purpose: Validate inputs and create a new resident user account.
    @param {str}      email           - Unique email address
    @param {str}      password        - Plaintext password to hash
    @param {str}      display_name    - Public display name
    @param {int|None} neighborhood_id - Optional neighborhood FK
    @returns {tuple} (User, None) on success, (None, error_key) on failure
    Algorithm:
    1. Check email uniqueness
    2. Hash password
    3. Create User with role='resident'
    4. Persist and return
    """
    if User.query.filter_by(email=email.lower().strip()).first():
        return None, 'DUPLICATE_EMAIL'

    user = User(
        email=email.lower().strip(),
        password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
        display_name=display_name.strip(),
        neighborhood_id=neighborhood_id,
        role='resident',
        is_active=True,
    )
    db.session.add(user)
    from sqlalchemy.exc import IntegrityError
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, 'DUPLICATE_EMAIL'
    return user, None


def authenticate_user(email, password):
    """
    Purpose: Verify email + password and return the matching user.
    @param {str} email    - Email address to look up
    @param {str} password - Plaintext password to check
    @returns {tuple} (User, None) on success, (None, error_key) on failure
    Algorithm:
    1. Query user by email
    2. Check password hash
    3. Check is_active flag
    4. Return user or error key
    """
    user = User.query.filter_by(email=email.lower().strip()).first()
    if not user or not check_password_hash(user.password_hash, password):
        return None, 'INVALID_CREDENTIALS'
    if not user.is_active:
        return None, 'FORBIDDEN'
    return user, None


def update_user_role(user_id, new_role):
    """
    Purpose: Change a user's role (admin-only action; caller must enforce permission).
    @param {int} user_id  - ID of the user to update
    @param {str} new_role - The new role string
    @returns {tuple} (User, None) on success, (None, error_key) on failure
    Algorithm:
    1. Validate role is in VALID_ROLES
    2. Fetch user by id
    3. Update role and commit
    4. Return updated user
    """
    if new_role not in VALID_ROLES:
        return None, 'INVALID_ROLE'
    user = User.query.get(user_id)
    if not user:
        return None, 'NOT_FOUND'
    user.role = new_role
    db.session.commit()
    return user, None


def _reset_serializer():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='pnec-password-reset')


def _reset_stamp(user):
    import hashlib
    return hashlib.sha256((user.password_hash + (user.auth_token or '')).encode()).hexdigest()


def request_password_reset(email):
    from flask import current_app
    from urllib.parse import urlencode
    user = User.query.filter_by(email=email.lower().strip(), is_active=True).first()
    if not user:
        return
    token = _reset_serializer().dumps({'id': user.id, 'stamp': _reset_stamp(user)})
    url = current_app.config['FRONTEND_URL'] + '/pages/reset-password.html?' + urlencode({'token': token})
    body = 'Reset your PNEC password using this link (expires in 24 hours):\n' + url + '\nIf you did not request this, ignore this email.'
    mode = current_app.config.get('MAIL_DELIVERY', 'auto')
    if mode == 'auto':
        mode = 'smtp' if current_app.config.get('MAIL_SERVER') else ('console' if current_app.debug else 'disabled')
    try:
        from app import mail
        from flask_mail import Message
        message = Message('Reset your PNEC password', recipients=[user.email], body=body)
        if current_app.testing:
            current_app.extensions.setdefault('account_mail_outbox', []).append(message)
        elif mode == 'console' and current_app.debug:
            print('Development account email:\n' + body, flush=True)
        elif mode == 'smtp' and mail is not None:
            mail.send(message)
        else:
            current_app.logger.warning('Account email delivery is not configured.')
    except Exception:
        # Do not leak addresses, reset links, SMTP credentials or account existence.
        current_app.logger.error('Account email delivery failed; check mail configuration.')


def reset_password_with_token(token, password):
    from flask import current_app
    from itsdangerous import BadData
    import secrets
    try:
        data = _reset_serializer().loads(token, max_age=current_app.config['PASSWORD_RESET_MAX_AGE'])
        if not isinstance(data, dict) or type(data.get('id')) is not int or not isinstance(data.get('stamp'), str):
            return False
        user = db.session.get(User, data['id'])
        if not user or not user.is_active or not secrets.compare_digest(data['stamp'], _reset_stamp(user)):
            return False
        # Conditional update also prevents simultaneous reuse of the same link.
        changed = User.query.filter_by(id=user.id, password_hash=user.password_hash, auth_token=user.auth_token).update({
            'password_hash': generate_password_hash(password, method='pbkdf2:sha256'),
            'auth_token': secrets.token_hex(32)}, synchronize_session=False)
        db.session.commit()
        return changed == 1
    except BadData:
        return False


def update_user_profile(user, data):
    """Validate all changes before updating the authenticated account only."""
    import re
    from sqlalchemy.exc import IntegrityError
    from app.models.neighborhood import Neighborhood

    def invalid(detail, key='VALIDATION_FAILED'):
        return None, {'key': key, 'detail': detail}

    allowed = {'display_name', 'email', 'phone', 'bio', 'avatar_url', 'neighborhood_id'}
    if not isinstance(data, dict) or not data or set(data) - allowed:
        return invalid('Submit only editable profile fields.')
    updates = {}
    for field in ('display_name', 'email', 'phone', 'bio', 'avatar_url'):
        if field not in data:
            continue
        value = data[field]
        if value is None and field in ('phone', 'bio', 'avatar_url'):
            updates[field] = None
            continue
        if not isinstance(value, str):
            return invalid(f'{field} must be text.')
        value = value.strip()
        if field == 'display_name' and not 1 <= len(value) <= 100:
            return invalid('Full name must contain 1–100 characters.')
        if field == 'email':
            value = value.lower()
            if len(value) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]{2,}', value):
                return invalid('Enter a valid email address.')
            if User.query.filter(User.email == value, User.id != user.id).first():
                return invalid('An account with that email already exists.', 'DUPLICATE_EMAIL')
        if field == 'phone' and value:
            # Keep digits and an optional international prefix consistently.
            if not re.fullmatch(r'\+?[0-9 ()\-.]+', value):
                return invalid('Enter a phone number with 7–15 digits and an optional + prefix.')
            digits = re.sub(r'[^0-9]', '', value)
            if not 7 <= len(digits) <= 15:
                return invalid('Enter a phone number with 7–15 digits and an optional + prefix.')
            value = ('+' if value.startswith('+') else '') + digits
        if field == 'bio' and len(value) > 500:
            return invalid('Bio must be 500 characters or fewer.')
        if field in ('phone', 'bio', 'avatar_url'):
            value = value or None
        updates[field] = value
    if 'neighborhood_id' in data:
        value = data['neighborhood_id']
        if value in (None, '', 'null'):
            updates['neighborhood_id'] = None
        else:
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                return invalid('Choose a valid neighborhood.')
            try:
                value = int(value)
            except ValueError:
                return invalid('Choose a valid neighborhood.')
            if not db.session.get(Neighborhood, value):
                return invalid('Selected neighborhood does not exist.')
            updates['neighborhood_id'] = value
    for field, value in updates.items():
        setattr(user, field, value)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return invalid('An account with that email already exists.', 'DUPLICATE_EMAIL')
    return user, None
