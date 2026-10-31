# app/routes/legacy_user.py
# Responsibility: Compatibility user-creation endpoint that accepts the older
# `/api/user` payload shape and delegates to the current auth service.

from flask import Blueprint, request, jsonify
from flask_login import login_user

from app.services.auth_service import create_user
from app.utils.errors import error_response

legacy_user_bp = Blueprint('legacy_user', __name__)


@legacy_user_bp.route('/user', methods=['POST'])
def create_legacy_user():
    """
    Purpose: Accept the older signup payload shape while creating a current PNEC account.
    Algorithm:
    1. Parse legacy fields from JSON body
    2. Normalize into current auth-service inputs
    3. Create the user with create_user()
    4. Establish a login session
    5. Return a compatibility-friendly response payload
    """
    data = request.get_json(silent=True) or {}

    display_name = (data.get('name') or data.get('display_name') or '').strip()
    uid = (data.get('uid') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()
    neighborhood_id = data.get('neighborhood_id') or None

    if not display_name and uid:
        display_name = uid
    if not email and uid:
        email = f'{uid}@legacy.opencodingsociety.com'

    if not email or not password or not display_name:
        return error_response(
            'VALIDATION_FAILED',
            400,
            {'detail': 'email, password, and name/display_name are required'}
        )

    if len(password) < 8:
        return error_response(
            'VALIDATION_FAILED',
            400,
            {'detail': 'Password must be at least 8 characters'}
        )

    user, err = create_user(email, password, display_name, neighborhood_id=neighborhood_id)
    if err:
        status = 409 if err == 'DUPLICATE_EMAIL' else 400
        return error_response(err, status)

    login_user(user, remember=False)
    return jsonify({
        'success': True,
        'message': 'Account created.',
        'user': user.to_dict(),
        'legacy': {
            'uid': uid or None,
            'sid': data.get('sid'),
            'school': data.get('school'),
            'kasm_server_needed': data.get('kasm_server_needed'),
        },
    }), 201
