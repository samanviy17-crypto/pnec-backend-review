# app/routes/page_overrides.py
# Responsibility: Page element override API — public read, admin write.

from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_login import current_user
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app import db
from app.models.page_override import PageOverride
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role

page_overrides_bp = Blueprint('page_overrides', __name__)


@page_overrides_bp.route('/overrides/<string:page_slug>', methods=['GET'])
def get_overrides(page_slug):
    """Return all overrides for a page as element_id → content map. Public."""
    rows = PageOverride.query.filter_by(page_slug=page_slug).all()
    return jsonify({
        'overrides': {r.element_id: r.content for r in rows},
        'entries':   [r.to_dict() for r in rows],
    }), 200


@page_overrides_bp.route('/overrides/<string:page_slug>', methods=['POST'])
@requires_role('admin')
def upsert_override(page_slug):
    """Create or update a single element override. Admin only."""
    data = request.get_json(silent=True) or {}
    element_id = (data.get('element_id') or '').strip()
    content    = data.get('content', '')

    if not element_id:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'element_id is required'})

    row = PageOverride.query.filter_by(page_slug=page_slug, element_id=element_id).first()
    if row:
        row.content    = content
        row.updated_at = datetime.utcnow()
        row.updated_by = current_user.id
    else:
        row = PageOverride(page_slug=page_slug, element_id=element_id,
                           content=content, updated_by=current_user.id)
        db.session.add(row)

    db.session.commit()
    return jsonify({'message': 'Override saved.', 'override': row.to_dict()}), 200


@page_overrides_bp.route('/overrides/<string:page_slug>/bulk', methods=['POST'])
@requires_role('admin')
def bulk_upsert_overrides(page_slug):
    """Bulk upsert. Body: { overrides: { element_id: content, ... } }"""
    data = request.get_json(silent=True) or {}
    updates = data.get('overrides') or {}
    if not isinstance(updates, dict):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'overrides must be an object'})

    saved = 0
    for eid, content in updates.items():
        eid = str(eid).strip()
        if not eid:
            continue
        row = PageOverride.query.filter_by(page_slug=page_slug, element_id=eid).first()
        if row:
            row.content    = content
            row.updated_at = datetime.utcnow()
            row.updated_by = current_user.id
        else:
            db.session.add(PageOverride(page_slug=page_slug, element_id=eid,
                                        content=content, updated_by=current_user.id))
        saved += 1

    db.session.commit()
    return jsonify({'message': f'Saved {saved} overrides.'}), 200


@page_overrides_bp.route('/overrides/<string:page_slug>/<string:element_id>', methods=['DELETE'])
@requires_role('admin')
def delete_override(page_slug, element_id):
    """Delete a single element override (reset to original). Admin only."""
    row = PageOverride.query.filter_by(page_slug=page_slug, element_id=element_id).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    return jsonify({'message': 'Override removed.'}), 200


@page_overrides_bp.route('/overrides/<string:page_slug>/all', methods=['DELETE'])
@requires_role('admin')
def delete_all_overrides_for_page(page_slug):
    """Delete every override on a page. Admin only. Returns the count removed."""
    rows = PageOverride.query.filter_by(page_slug=page_slug).all()
    n = len(rows)
    for r in rows:
        db.session.delete(r)
    db.session.commit()
    return jsonify({'message': f'Removed {n} overrides.', 'removed': n}), 200


@page_overrides_bp.route('/overrides/all', methods=['GET'])
@requires_role('admin')
def list_all_overrides():
    """Return every override across every page. Admin only — used by the
    editor's site-wide overrides panel.
    Returns: { pages: { slug: [{element_id, content, updated_at}, ...] } }
    """
    rows = PageOverride.query.order_by(PageOverride.page_slug, PageOverride.element_id).all()
    by_page = {}
    for r in rows:
        by_page.setdefault(r.page_slug, []).append(r.to_dict())
    return jsonify({'pages': by_page, 'total': len(rows)}), 200
