# app/routes/volunteer.py
# Volunteer interest submission + admin management endpoints.

import re
from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import desc, or_

from app import db
from app.models.volunteer_interest import (
    VolunteerInterest, VALID_STATUSES, VALID_ROLES,
    STATUS_NEW, STATUS_CONTACTED, STATUS_ONBOARDING, STATUS_ACTIVE,
    STATUS_DECLINED, STATUS_ARCHIVED, ROLE_LABEL,
)
from app.utils.errors import error_response

from app.utils.input_validation import json_object, text, query_integer
from werkzeug.exceptions import HTTPException, BadRequest

volunteer_bp = Blueprint('volunteer', __name__)


@volunteer_bp.errorhandler(HTTPException)
def controlled_error(error):
    return jsonify({'message': error.description}), error.code


# ─── Public: submit ───────────────────────────────────────────────

@volunteer_bp.route('/volunteer/submit', methods=['POST'])
def submit_interest():
    """
    Public endpoint — receives a volunteer-interest form post.

    Body (JSON):
      { name, email, phone?, neighborhood?, role, message? }

    Returns: 200 { ok: true, id }  on success
             400 with code on validation errors
             429 on rate-limit
             5xx are caught and turned into a generic 500 (no leak)
    """
    try:
        data = json_object({'name', 'email', 'role', 'phone', 'neighborhood', 'message'})
        name = text(data.get('name', ''), 'name', 120, required=True)
        email = text(data.get('email', ''), 'email', 255, required=True).lower()
        role = text(data.get('role', ''), 'role', 40, required=True)
        phone = text(data.get('phone'), 'phone', 32, nullable=True) or None
        neighborhood = text(data.get('neighborhood'), 'neighborhood', 120, nullable=True) or None
        message = text(data.get('message'), 'message', 5000, nullable=True) or None

        # Basic validation
        if len(name) < 2 or len(name) > 120:
            return error_response('INVALID_NAME', 400, {'detail': 'Name is required (2–120 chars).'})
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]{2,}', email):
            return error_response('INVALID_EMAIL', 400, {'detail': 'A valid email is required.'})
        if role not in VALID_ROLES:
            return error_response('INVALID_ROLE', 400, {
                'detail': f'Role must be one of: {", ".join(sorted(VALID_ROLES))}',
            })
        if message and len(message) > 5000:
            return error_response('MESSAGE_TOO_LONG', 400, {'detail': 'Message must be ≤ 5000 chars.'})
        if phone and len(phone) > 32:
            return error_response('PHONE_TOO_LONG', 400, {'detail': 'Phone must be ≤ 32 chars.'})

        # Soft rate-limit: same email submitting > 5 times in last 24h
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=24)
        recent = VolunteerInterest.query.filter(
            VolunteerInterest.email == email,
            VolunteerInterest.created_at >= cutoff,
        ).count()
        if recent >= 5:
            return error_response('RATE_LIMITED', 429, {
                'detail': 'Too many submissions in 24h. Please email contact@example.test directly.',
            })

        vi = VolunteerInterest(
            name=name, email=email, phone=phone,
            neighborhood=neighborhood, role=role, message=message,
            status=STATUS_NEW,
            ip_address=(request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:45],
            user_agent=(request.headers.get('User-Agent') or '')[:255],
        )
        db.session.add(vi)
        db.session.commit()

        return jsonify({'ok': True, 'id': vi.id}), 200

    except HTTPException:
        raise
    except Exception:
        try:
            current_app.logger.exception('volunteer.submit_interest failed')
        except Exception:
            pass
        db.session.rollback()
        return error_response('SERVER_ERROR', 500, {
            'detail': 'Submission failed. Please try again or email contact@example.test.'
        })


# ─── Admin: list, detail, update ───────────────────────────────────

def _require_admin():
    """Require an active database-backed administrator identity."""
    from app.utils.auth_helpers import current_auth_user
    user = current_auth_user()
    return bool(user and user.role == 'admin')


@volunteer_bp.route('/volunteer/interests', methods=['GET'])
def list_interests():
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)

    status = (request.args.get('status') or '').strip() or None
    role   = (request.args.get('role') or '').strip() or None
    q      = (request.args.get('q') or '').strip() or None
    limit = query_integer('limit', 100, 1, 500)
    if (status and status not in VALID_STATUSES) or (role and role not in VALID_ROLES) or (q and len(q) > 200):
        raise BadRequest('Invalid status, role or search length.')

    query = VolunteerInterest.query
    if status and status in VALID_STATUSES:
        query = query.filter(VolunteerInterest.status == status)
    if role and role in VALID_ROLES:
        query = query.filter(VolunteerInterest.role == role)
    if q:
        like = f'%{q}%'
        query = query.filter(or_(
            VolunteerInterest.name.ilike(like),
            VolunteerInterest.email.ilike(like),
            VolunteerInterest.neighborhood.ilike(like),
            VolunteerInterest.message.ilike(like),
        ))

    items = query.order_by(desc(VolunteerInterest.created_at)).limit(limit).all()

    # Compute summary counts by status (always all-time for the dashboard pills)
    summary = {s: VolunteerInterest.query.filter_by(status=s).count() for s in VALID_STATUSES}
    summary['total'] = sum(summary.values())

    return jsonify({
        'items':   [it.to_dict(include_admin=True) for it in items],
        'summary': summary,
        'roles':   {k: v for k, v in ROLE_LABEL.items()},
    }), 200


@volunteer_bp.route('/volunteer/interests/<int:vid>', methods=['PATCH'])
def update_interest(vid):
    if not _require_admin():
        return error_response('UNAUTHORIZED', 401)

    vi = VolunteerInterest.query.get(vid)
    if not vi:
        return error_response('NOT_FOUND', 404)

    data = json_object({'status', 'note'})
    if not data:
        raise BadRequest('Provide status or note.')
    status = data.get('status')
    note = text(data.get('note'), 'note', 5000, nullable=True) or None
    if status is not None and not isinstance(status, str):
        raise BadRequest('status must be text.')

    if status is not None:
        if status not in VALID_STATUSES:
            return error_response('INVALID_STATUS', 400)
        old = vi.status
        vi.status = status
        now = datetime.utcnow()
        if status == STATUS_CONTACTED and not vi.contacted_at:
            vi.contacted_at = now
        if status in {STATUS_ACTIVE, STATUS_DECLINED, STATUS_ARCHIVED}:
            vi.resolved_at = now
        # Append an audit line to admin_notes
        audit = f'[{now.strftime("%Y-%m-%d %H:%M UTC")}] status {old} → {status}'
        vi.admin_notes = (vi.admin_notes + '\n' + audit) if vi.admin_notes else audit

    if note:
        now = datetime.utcnow()
        audit = f'[{now.strftime("%Y-%m-%d %H:%M UTC")}] {note}'
        vi.admin_notes = (vi.admin_notes + '\n' + audit) if vi.admin_notes else audit

    db.session.commit()
    return jsonify({'ok': True, 'item': vi.to_dict(include_admin=True)}), 200
