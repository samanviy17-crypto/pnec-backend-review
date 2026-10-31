# app/routes/cms_theme.py
# Responsibility: Theme tokens API — global colors/fonts/logo/spacing.
# Public read of published tokens, admin (or token) read of draft, admin
# writes. Mirrors the page-template draft/publish split.

from datetime import datetime
from flask import Blueprint, jsonify, request, Response
from flask_login import current_user

from app import db
from app.models.theme_settings import (
    ThemeSettings, DEFAULT_TOKENS, TOKEN_META,
    STATE_DRAFT, STATE_PUBLISHED, VALID_STATES, tokens_to_css,
)
from app.models.preview_token import PreviewToken
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role


cms_theme_bp = Blueprint('cms_theme', __name__)


def _get_or_create(state):
    row = ThemeSettings.query.filter_by(state=state).first()
    if row:
        return row
    if state == STATE_DRAFT:
        row = ThemeSettings(state=STATE_DRAFT)
        db.session.add(row)
        db.session.commit()
        return row
    return None


def _is_admin():
    return (current_user.is_authenticated
            and getattr(current_user, 'role', None) == 'admin')


def _check_token(token):
    """A preview token for any page also grants read access to draft theme."""
    if not token:
        return False
    row = PreviewToken.query.filter_by(token=token).first()
    return bool(row and row.expires_at > datetime.utcnow())


# ─── Schema (the editable token catalog) ─────────────────────────────────────

@cms_theme_bp.route('/cms/theme/schema', methods=['GET'])
def get_theme_schema():
    """Return the list of editable theme tokens grouped by category."""
    grouped = {}
    for key, meta in TOKEN_META.items():
        grouped.setdefault(meta['group'], []).append({
            'key':     key,
            'label':   meta['label'],
            'type':    meta['type'],
            'options': meta.get('options'),
            'default': DEFAULT_TOKENS[key],
        })
    return jsonify({'groups': grouped}), 200


# ─── Read tokens ─────────────────────────────────────────────────────────────

@cms_theme_bp.route('/cms/theme', methods=['GET'])
def get_theme():
    state = (request.args.get('state') or STATE_PUBLISHED).strip()
    if state not in VALID_STATES:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'invalid state'})
    if state == STATE_DRAFT:
        token = request.args.get('token')
        if not (_is_admin() or _check_token(token)):
            return error_response('UNAUTHORIZED', 401)
    row = ThemeSettings.query.filter_by(state=state).first()
    if not row:
        # Friendly: empty state returns the defaults
        return jsonify({
            'state':  state,
            'tokens': dict(DEFAULT_TOKENS),
            'updated_at': None,
        }), 200
    return jsonify(row.to_dict()), 200


@cms_theme_bp.route('/cms/theme.css', methods=['GET'])
def get_theme_css():
    """Serve theme tokens as a CSS file `:root { --cms-color-primary: ... }`.
    Public pages can `<link rel="stylesheet" href="/api/cms/theme.css">` it."""
    state = (request.args.get('state') or STATE_PUBLISHED).strip()
    if state not in VALID_STATES:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'invalid state'})
    if state == STATE_DRAFT:
        token = request.args.get('token')
        if not (_is_admin() or _check_token(token)):
            return error_response('UNAUTHORIZED', 401)
    row = ThemeSettings.query.filter_by(state=state).first()
    tokens = row.get_tokens() if row else dict(DEFAULT_TOKENS)
    return Response(tokens_to_css(tokens), mimetype='text/css', headers={
        'Cache-Control': 'public, max-age=60',
    })


# ─── Write tokens (admin) ────────────────────────────────────────────────────

@cms_theme_bp.route('/cms/theme/draft', methods=['PATCH'])
@requires_role('admin')
def patch_theme_draft():
    data = request.get_json(silent=True) or {}
    updates = data.get('updates') or {}
    if not isinstance(updates, dict):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'updates must be an object'})

    row = _get_or_create(STATE_DRAFT)
    tokens = row.get_tokens()
    for k, v in updates.items():
        if k in DEFAULT_TOKENS:
            tokens[k] = str(v) if v is not None else ''
    row.set_tokens(tokens)
    row.updated_at = datetime.utcnow()
    row.updated_by = current_user.id
    db.session.commit()
    return jsonify(row.to_dict()), 200


@cms_theme_bp.route('/cms/theme/publish', methods=['POST'])
@requires_role('admin')
def publish_theme():
    draft = ThemeSettings.query.filter_by(state=STATE_DRAFT).first()
    if not draft:
        return error_response('NOT_FOUND', 404, {'detail': 'no draft to publish'})
    pub = ThemeSettings.query.filter_by(state=STATE_PUBLISHED).first()
    now = datetime.utcnow()
    if pub:
        pub.tokens_json  = draft.tokens_json
        pub.published_at = now
        pub.published_by = current_user.id
        pub.updated_at   = now
        pub.updated_by   = current_user.id
    else:
        pub = ThemeSettings(
            state=STATE_PUBLISHED,
            tokens_json=draft.tokens_json,
            published_at=now,
            published_by=current_user.id,
            updated_by=current_user.id,
        )
        db.session.add(pub)
    db.session.commit()
    return jsonify({'message': 'Theme published.', 'published_at': now.isoformat()}), 200
