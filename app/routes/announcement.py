# app/routes/announcement.py
# Responsibility: Announcement/alert banner API — public read, admin write.

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_login import current_user

from app import db
from app.models.announcement import Announcement, VALID_LEVELS
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role, requires_min_role

announcements_bp = Blueprint('announcements', __name__)


@announcements_bp.route('/announcements', methods=['GET'])
def get_active_announcements():
    """Return all active, non-expired announcements (public)."""
    now = datetime.utcnow()
    rows = Announcement.query.filter_by(is_active=True).order_by(Announcement.created_at.desc()).all()
    active = [r.to_dict() for r in rows if r.expires_at is None or r.expires_at > now]
    return jsonify({'announcements': active}), 200


@announcements_bp.route('/announcements/all', methods=['GET'])
@requires_min_role('staff')
def get_all_announcements():
    """Return every announcement including inactive ones (staff+)."""
    rows = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return jsonify({'announcements': [r.to_dict() for r in rows]}), 200


@announcements_bp.route('/announcements', methods=['POST'])
@requires_role('admin')
def create_announcement():
    """Create a new sitewide announcement. Admin only."""
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    level   = (data.get('level') or 'info').strip()

    if not message:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'message is required'})
    if level not in VALID_LEVELS:
        return error_response('VALIDATION_FAILED', 400, {'detail': f'level must be one of {VALID_LEVELS}'})

    expires_at = None
    if data.get('expires_at'):
        try:
            expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            return error_response('VALIDATION_FAILED', 400, {'detail': 'expires_at must be ISO 8601'})

    ann = Announcement(
        message=message,
        level=level,
        is_active=data.get('is_active', True),
        expires_at=expires_at,
        created_by=current_user.id,
    )
    db.session.add(ann)
    db.session.commit()
    return jsonify({'message': 'Announcement created.', 'announcement': ann.to_dict()}), 201


@announcements_bp.route('/announcements/<int:ann_id>', methods=['PATCH'])
@requires_role('admin')
def update_announcement(ann_id):
    """Update an announcement. Admin only."""
    ann = Announcement.query.get(ann_id)
    if not ann:
        return error_response('NOT_FOUND', 404)

    data = request.get_json(silent=True) or {}
    if 'message' in data:
        ann.message = (data['message'] or '').strip() or ann.message
    if 'level' in data:
        if data['level'] not in VALID_LEVELS:
            return error_response('VALIDATION_FAILED', 400, {'detail': f'level must be one of {VALID_LEVELS}'})
        ann.level = data['level']
    if 'is_active' in data:
        ann.is_active = bool(data['is_active'])
    if 'expires_at' in data:
        if data['expires_at'] is None:
            ann.expires_at = None
        else:
            try:
                ann.expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                return error_response('VALIDATION_FAILED', 400, {'detail': 'expires_at must be ISO 8601'})

    ann.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Announcement updated.', 'announcement': ann.to_dict()}), 200


@announcements_bp.route('/announcements/<int:ann_id>', methods=['DELETE'])
@requires_role('admin')
def delete_announcement(ann_id):
    """Delete an announcement. Admin only."""
    ann = Announcement.query.get(ann_id)
    if not ann:
        return error_response('NOT_FOUND', 404)
    db.session.delete(ann)
    db.session.commit()
    return jsonify({'message': 'Announcement deleted.'}), 200
