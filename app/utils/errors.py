# app/utils/errors.py
# Responsibility: Centralized error messages and JSON error response helpers.
# All routes import from here — error strings are never scattered inline.

from flask import jsonify

# ─── Error message registry ───────────────────────────────────────────────────
ERROR_MESSAGES = {
    'NOT_FOUND':          'The requested resource was not found.',
    'UNAUTHORIZED':       'Please sign in to continue.',
    'FORBIDDEN':          'You do not have permission to do this.',
    'VALIDATION_FAILED':  'The submitted data was invalid.',
    'SERVER_ERROR':       'An unexpected error occurred. Please try again later.',
    'DUPLICATE_EMAIL':    'An account with that email address already exists.',
    'INVALID_CREDENTIALS':'Invalid email or password.',
    'INVALID_ROLE':       'The specified role is not valid.',
    'RATE_LIMITED':       'Too many requests. Please wait before trying again.',
    'UPLOAD_FAILED':      'File upload failed. Check file type and size.',
}


def error_response(key, status_code=400, extra=None):
    """
    Purpose: Build a consistent JSON error response.
    @param {str}  key         - An ERROR_MESSAGES key
    @param {int}  status_code - HTTP status code to return
    @param {dict} extra       - Optional additional fields to include in response
    @returns {tuple} (Response, int) JSON body + status code
    Algorithm:
    1. Look up message by key (fallback to SERVER_ERROR)
    2. Build response dict
    3. Merge any extra fields
    4. Return jsonify tuple
    """
    message = ERROR_MESSAGES.get(key, ERROR_MESSAGES['SERVER_ERROR'])
    body = {'error': key, 'message': message}
    if extra:
        body.update(extra)
    return jsonify(body), status_code
