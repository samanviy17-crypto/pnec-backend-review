# app/utils/auth_decorators.py
# Responsibility: Role-based access control decorators for Flask routes.
# Every protected route uses requires_role() — never inline permission checks.

from functools import wraps
from flask import jsonify
from flask_login import current_user

# Role hierarchy — higher index = more access
ROLE_HIERARCHY = ['resident', 'coordinator', 'staff', 'admin']


def _role_rank(role):
    """
    Purpose: Return the numeric rank of a role for hierarchy comparison.
    @param {str} role - Role string
    @returns {int} Rank index (0–3), or -1 if unknown
    """
    try:
        return ROLE_HIERARCHY.index(role)
    except ValueError:
        return -1


def requires_auth(f):
    """
    Purpose: Require an authenticated session; reject anonymous requests.
    @param {function} f - The route handler to protect
    @returns {function} Wrapped handler that checks for authentication
    Algorithm:
    1. Check current_user.is_authenticated
    2. If not: return 401 JSON error
    3. If yes: call the original handler
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'UNAUTHORIZED', 'message': 'Please sign in to continue.'}), 401
        return f(*args, **kwargs)
    return decorated


def requires_role(*roles):
    """
    Purpose: Restrict a route to users whose role is in the allowed list.
    @param {*str} roles - One or more allowed role strings
    @returns {function} Decorator that enforces role membership
    Algorithm:
    1. Check that user is authenticated
    2. Check that user's role is in the allowed set
    3. If either check fails: return appropriate JSON error
    4. Otherwise: call the route handler
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # Path A: authenticated session (cookie-based admin login)
            if current_user.is_authenticated:
                if current_user.role not in roles:
                    return jsonify({'error': 'FORBIDDEN',
                                    'message': 'You do not have permission to do this.'}), 403
                return f(*args, **kwargs)
            return jsonify({'error': 'UNAUTHORIZED',
                            'message': 'Please sign in to continue.'}), 401
        return decorated
    return decorator


def requires_min_role(min_role):
    """
    Purpose: Allow access to users with a role at or above the minimum in the hierarchy.
    @param {str} min_role - Minimum required role (e.g. 'coordinator')
    @returns {function} Decorator that enforces hierarchy rank
    Algorithm:
    1. Resolve the numeric rank of the minimum role
    2. Resolve the numeric rank of the current user's role
    3. If user rank < required rank: return 403
    4. Otherwise: proceed
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'error': 'UNAUTHORIZED',
                                'message': 'Please sign in to continue.'}), 401
            if _role_rank(current_user.role) < _role_rank(min_role):
                return jsonify({'error': 'FORBIDDEN',
                                'message': 'You do not have permission to do this.'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
