# app/models/security_event.py
# Audit log + security-event timeline. Every sensitive action lands a
# row here so admins can see who-did-what when troubleshooting an
# incident, and the security dashboard can show real-time threat
# activity.

import json
from datetime import datetime
from app import db


# Standard kinds. Keep these short + greppable.
KIND_LOGIN_SUCCESS    = 'login_success'
KIND_LOGIN_FAILURE    = 'login_failure'
KIND_LOGIN_LOCKED     = 'login_locked'        # account hit lockout threshold
KIND_LOGIN_RATE_LIMIT = 'login_rate_limit'    # IP hit rate-limit ceiling
KIND_REGISTER         = 'register'
KIND_REGISTER_DUP     = 'register_duplicate'
KIND_PASSWORD_RESET   = 'password_reset'
KIND_PROFILE_UPDATE   = 'profile_update'
KIND_ROLE_CHANGE      = 'role_change'         # admin promoted/demoted a user
KIND_ADMIN_ACTION     = 'admin_action'        # generic admin write
KIND_PUBLISH          = 'publish_page'
KIND_REVERT           = 'revert_revision'
KIND_THEME_PUBLISH    = 'theme_publish'
KIND_PUSH_SUBSCRIBE   = 'push_subscribe'
KIND_SUSPICIOUS       = 'suspicious'          # heuristic flag
KIND_API_ERROR        = 'api_error'           # 5xx that wasn't an OK failure

# Severity levels — drives the dashboard color coding.
SEVERITY_INFO     = 'info'        # normal admin activity
SEVERITY_WARNING  = 'warning'     # rate-limit hit, lockout, suspicious UA
SEVERITY_ALERT    = 'alert'       # repeated failures, role changes
SEVERITY_CRITICAL = 'critical'    # admin compromise indicators


class SecurityEvent(db.Model):
    """One row per security-relevant action.

    Auto-prunes after 90 days via the cleanup helper to keep the table
    bounded. The dashboard also caps queries at 500 rows.
    """

    __tablename__ = 'security_events'
    __table_args__ = (
        db.Index('ix_secevents_created',  'created_at'),
        db.Index('ix_secevents_kind',     'kind'),
        db.Index('ix_secevents_actor',    'actor_id'),
        db.Index('ix_secevents_severity', 'severity'),
    )

    id           = db.Column(db.Integer, primary_key=True)
    kind         = db.Column(db.String(40),  nullable=False)
    actor_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    actor_email  = db.Column(db.String(254), nullable=True)   # captured at write time, not joined
    detail       = db.Column(db.String(1000), nullable=True)
    ip           = db.Column(db.String(64),  nullable=True)
    user_agent   = db.Column(db.String(300), nullable=True)
    severity     = db.Column(db.String(16),  nullable=False, default='info')
    extra_json   = db.Column(db.Text,        nullable=True)
    created_at   = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)

    def to_dict(self):
        try:
            extra = json.loads(self.extra_json) if self.extra_json else None
        except (ValueError, TypeError):
            extra = None
        return {
            'id':          self.id,
            'kind':        self.kind,
            'actor_id':    self.actor_id,
            'actor_email': self.actor_email,
            'detail':      self.detail,
            'ip':          self.ip,
            'user_agent':  self.user_agent,
            'severity':    self.severity,
            'extra':       extra,
            'created_at':  self.created_at.isoformat() if self.created_at else None,
        }


# ─── Cleanup ─────────────────────────────────────────────────────────────


def prune_old_events(retention_days: int = 90) -> int:
    """Delete security events older than `retention_days`. Returns count.
    Caller is responsible for db.session.commit() unless the call is
    inside a request that will commit later.
    """
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    q = SecurityEvent.query.filter(SecurityEvent.created_at < cutoff)
    count = q.count()
    q.delete(synchronize_session=False)
    return count
