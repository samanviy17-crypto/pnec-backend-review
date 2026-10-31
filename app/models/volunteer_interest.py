# app/models/volunteer_interest.py
# Volunteer interest submissions from /pages/volunteer.html
#
# Lifecycle:
#   NEW        - just submitted, no admin contact yet
#   CONTACTED  - admin has reached out
#   ONBOARDING - candidate is going through PNEC's process (CERT class, etc.)
#   ACTIVE     - volunteering with PNEC now
#   DECLINED   - candidate chose not to proceed (or admin decided not to)
#   ARCHIVED   - kept for records but out of the active funnel
#
# All status changes are logged in admin_notes (append-only).

from datetime import datetime
from app import db


STATUS_NEW         = 'new'
STATUS_CONTACTED   = 'contacted'
STATUS_ONBOARDING  = 'onboarding'
STATUS_ACTIVE      = 'active'
STATUS_DECLINED    = 'declined'
STATUS_ARCHIVED    = 'archived'

VALID_STATUSES = {
    STATUS_NEW, STATUS_CONTACTED, STATUS_ONBOARDING,
    STATUS_ACTIVE, STATUS_DECLINED, STATUS_ARCHIVED,
}

ROLE_NEC          = 'neighborhood_coordinator'
ROLE_CERT         = 'cert_volunteer'
ROLE_HAM          = 'ham_radio_operator'
ROLE_BOARD        = 'admin_board'
ROLE_FLEX         = 'flex'

VALID_ROLES = {ROLE_NEC, ROLE_CERT, ROLE_HAM, ROLE_BOARD, ROLE_FLEX}

ROLE_LABEL = {
    ROLE_NEC:   'Neighborhood Coordinator',
    ROLE_CERT:  'CERT Volunteer',
    ROLE_HAM:   'Ham Radio Operator',
    ROLE_BOARD: 'Administrative / Board Support',
    ROLE_FLEX:  'Flexible — anything I can help with',
}


class VolunteerInterest(db.Model):
    """A public-form submission expressing volunteer interest."""

    __tablename__ = 'volunteer_interests'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(120),  nullable=False)
    email       = db.Column(db.String(255),  nullable=False, index=True)
    phone       = db.Column(db.String(32),   nullable=True)
    neighborhood= db.Column(db.String(120),  nullable=True)
    role        = db.Column(db.String(40),   nullable=False, index=True)
    message     = db.Column(db.Text,         nullable=True)

    status      = db.Column(db.String(20),   nullable=False, default=STATUS_NEW, index=True)
    admin_notes = db.Column(db.Text,         nullable=True)

    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    contacted_at= db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)

    ip_address  = db.Column(db.String(45),   nullable=True)
    user_agent  = db.Column(db.String(255),  nullable=True)

    def to_dict(self, include_admin=False):
        out = {
            'id':           self.id,
            'name':         self.name,
            'email':        self.email,
            'phone':        self.phone,
            'neighborhood': self.neighborhood,
            'role':         self.role,
            'role_label':   ROLE_LABEL.get(self.role, self.role),
            'message':      self.message,
            'status':       self.status,
            'created_at':   self.created_at.isoformat() if self.created_at else None,
            'updated_at':   self.updated_at.isoformat() if self.updated_at else None,
            'contacted_at': self.contacted_at.isoformat() if self.contacted_at else None,
            'resolved_at':  self.resolved_at.isoformat() if self.resolved_at else None,
        }
        if include_admin:
            out['admin_notes'] = self.admin_notes
            out['ip_address']  = self.ip_address
            out['user_agent']  = self.user_agent
        return out

    def __repr__(self):
        return f'<VolunteerInterest {self.id} {self.email} {self.role} {self.status}>'
