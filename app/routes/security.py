# app/routes/security.py
# Admin-only endpoints for the security dashboard:
#   GET  /api/security/events?limit=&kind=&severity=  Recent events
#   GET  /api/security/summary                        Aggregate counts (24h, 7d)
#   POST /api/security/events/prune                   Manually prune events
#   GET  /api/security/lockouts                       Current account lockouts
#   POST /api/security/unlock                         Admin clears a lockout

from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

from app import db
from app.models.security_event import (
    SecurityEvent, prune_old_events,
    KIND_LOGIN_FAILURE, KIND_LOGIN_LOCKED, KIND_LOGIN_RATE_LIMIT,
    KIND_LOGIN_SUCCESS, KIND_REGISTER, KIND_REGISTER_DUP,
    SEVERITY_ALERT, SEVERITY_CRITICAL, SEVERITY_WARNING,
)
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role
from app.utils.security import (
    is_account_locked, lockout_status, record_login_success, currently_locked_emails,
    log_event,
)


security_bp = Blueprint('security', __name__)


@security_bp.route('/security/events', methods=['GET'])
@requires_role('admin')
def list_events():
    """Return recent security events, newest first.
    Query params:
      limit:    1..500 (default 100)
      kind:     filter to one event kind
      severity: filter to one severity level
      since:    ISO 8601 cutoff — default last 7 days
    """
    limit = max(1, min(500, int(request.args.get('limit') or 100)))
    kind = (request.args.get('kind') or '').strip()
    severity = (request.args.get('severity') or '').strip()
    since_arg = request.args.get('since')
    if since_arg:
        try:
            since = datetime.fromisoformat(since_arg.replace('Z', '+00:00'))
            if since.tzinfo:
                since = since.replace(tzinfo=None)
        except (ValueError, TypeError):
            since = datetime.utcnow() - timedelta(days=7)
    else:
        since = datetime.utcnow() - timedelta(days=7)

    q = SecurityEvent.query.filter(SecurityEvent.created_at >= since)
    if kind:
        q = q.filter_by(kind=kind)
    if severity:
        q = q.filter_by(severity=severity)
    rows = q.order_by(SecurityEvent.created_at.desc()).limit(limit).all()
    return jsonify({'events': [r.to_dict() for r in rows], 'count': len(rows)}), 200


@security_bp.route('/security/summary', methods=['GET'])
@requires_role('admin')
def summary():
    """Aggregate counts for the dashboard headline metrics."""
    now = datetime.utcnow()
    h24 = now - timedelta(hours=24)
    d7 = now - timedelta(days=7)

    # Last 24h
    events_24h = SecurityEvent.query.filter(SecurityEvent.created_at >= h24)
    failures_24h = events_24h.filter(SecurityEvent.kind.in_([
        KIND_LOGIN_FAILURE, KIND_LOGIN_LOCKED, KIND_LOGIN_RATE_LIMIT
    ])).count()
    successes_24h = events_24h.filter_by(kind=KIND_LOGIN_SUCCESS).count()
    registers_24h = events_24h.filter_by(kind=KIND_REGISTER).count()
    alerts_24h = events_24h.filter(SecurityEvent.severity.in_([
        SEVERITY_ALERT, SEVERITY_CRITICAL,
    ])).count()

    # Last 7d
    events_7d = SecurityEvent.query.filter(SecurityEvent.created_at >= d7)
    total_7d = events_7d.count()

    # Top kinds in last 7 days (group-by isn't elegant in SQLAlchemy
    # 1.x without text(); count manually via tally)
    tally: dict[str, int] = {}
    for r in events_7d.with_entities(SecurityEvent.kind).all():
        k = r[0] or 'unknown'
        tally[k] = tally.get(k, 0) + 1
    top_kinds = sorted(tally.items(), key=lambda x: -x[1])[:10]

    # Currently-locked accounts from the configured shared/development store
    locked = []
    now_ts = datetime.utcnow().timestamp()
    for email in currently_locked_emails():
        locked_state, seconds = is_account_locked(email)
        if locked_state:
            locked.append({
                'email':         email,
                'unlock_in_sec': seconds,
            })

    return jsonify({
        'last_24h': {
            'login_failures':  failures_24h,
            'login_successes': successes_24h,
            'registrations':   registers_24h,
            'alerts':          alerts_24h,
        },
        'last_7d': {
            'total_events': total_7d,
            'top_kinds':    top_kinds,
        },
        'currently_locked': locked,
        'generated_at':     now.isoformat(),
    }), 200


@security_bp.route('/security/lockouts', methods=['GET'])
@requires_role('admin')
def lockouts():
    """Detailed lockout state — emails currently locked + their countdown."""
    now_ts = datetime.utcnow().timestamp()
    rows = []
    for email in currently_locked_emails():
        locked_state, seconds = is_account_locked(email)
        if locked_state:
            rows.append(lockout_status(email))
    rows.sort(key=lambda r: -r['unlock_in_sec'])
    return jsonify({'lockouts': rows, 'count': len(rows)}), 200


@security_bp.route('/security/unlock', methods=['POST'])
@requires_role('admin')
def unlock_account():
    """Admin-only: clear a lockout for an email (e.g. after the user
    contacted support and proved identity)."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'email is required'})
    record_login_success(email)
    log_event('admin_unlock', severity=SEVERITY_WARNING,
              detail=f'Admin manually unlocked account: {email}')
    return jsonify({'ok': True, 'email': email}), 200


@security_bp.route('/security/events/prune', methods=['POST'])
@requires_role('admin')
def prune():
    """Manually prune old events (>retention_days). Default 90."""
    data = request.get_json(silent=True) or {}
    retention = max(7, min(365, int(data.get('retention_days') or 90)))
    deleted = prune_old_events(retention_days=retention)
    db.session.commit()
    log_event('events_pruned', severity='info',
              detail=f'Pruned {deleted} security events older than {retention}d')
    return jsonify({'ok': True, 'pruned': deleted, 'retention_days': retention}), 200
