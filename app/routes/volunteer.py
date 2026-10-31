# app/routes/volunteer.py
# Volunteer interest submission + admin management endpoints.

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

try:
    from app.routes.auth import requires_role
except Exception:
    requires_role = None  # gracefully no-op if auth module missing

volunteer_bp = Blueprint('volunteer', __name__)


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
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        role = (data.get('role') or '').strip()
        phone = (data.get('phone') or '').strip() or None
        neighborhood = (data.get('neighborhood') or '').strip() or None
        message = (data.get('message') or '').strip() or None

        # Basic validation
        if len(name) < 2 or len(name) > 120:
            return error_response('INVALID_NAME', 400, {'detail': 'Name is required (2–120 chars).'})
        if not email or '@' not in email or len(email) > 255:
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

        try:
            current_app.logger.info(
                f'volunteer.submit ok id={vi.id} email={email} role={role}'
            )
        except Exception:
            pass

        return jsonify({'ok': True, 'id': vi.id}), 200

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
    limit  = min(int(request.args.get('limit', 100)), 500)

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

    data = request.get_json(silent=True) or {}
    status = data.get('status')
    note = (data.get('note') or '').strip() or None

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
