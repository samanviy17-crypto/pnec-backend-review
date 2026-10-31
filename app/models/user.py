# app/models/user.py
# Responsibility: User database model — authentication, roles, and profile data.

import secrets
import time
from datetime import datetime
from flask_login import UserMixin
from app import db

VALID_ROLES = ('resident', 'coordinator', 'staff', 'admin')


class User(UserMixin, db.Model):
    """PNEC user account with role-based access control."""

    __tablename__ = 'users'

    id              = db.Column(db.Integer,     primary_key=True)
    email           = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash   = db.Column(db.String(255), nullable=False)
    display_name    = db.Column(db.String(100), nullable=False)
    neighborhood_id = db.Column(db.Integer,     db.ForeignKey('neighborhoods.id'), nullable=True)
    role            = db.Column(db.String(20),  nullable=False, default='resident')
    is_active       = db.Column(db.Boolean,     nullable=False, default=True)
    created_at      = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    bio             = db.Column(db.Text,        nullable=True)
    avatar_url      = db.Column(db.Text,        nullable=True)
    phone           = db.Column(db.String(20),  nullable=True)
    auth_token      = db.Column(db.String(64),  nullable=True, unique=True, index=True)

    def get_id(self):
        # Bind cookies to the existing account credential; logout/reset revoke replays.
        import hashlib
        stamp = hashlib.sha256((self.password_hash + (self.auth_token or '')).encode()).hexdigest()
        return f'{self.id}:{stamp}'

    def generate_token(self):
        # Version + issuance time + 216 random bits fit the existing VARCHAR(64).
        # Validation requires an exact database match, so issuance cannot be forged.
        self.auth_token = 'p1' + format(int(time.time()), '08x') + secrets.token_hex(27)
        return self.auth_token

    # Relationships
    neighborhood    = db.relationship('Neighborhood', back_populates='residents', foreign_keys=[neighborhood_id])
    media_posts     = db.relationship('MediaPost',    back_populates='uploader',  lazy='dynamic')
    events_created  = db.relationship('Event',        back_populates='creator',   lazy='dynamic')

    # ── Role helpers ──────────────────────────────────────────────────────────

    def has_role(self, *roles):
        """Return True if the user's role is in the given list."""
        return self.role in roles

    def can_upload_media(self):
        return self.role in ('coordinator', 'staff', 'admin')

    def can_manage_events(self):
        return self.role in ('coordinator', 'staff', 'admin')

    def can_access_staff_dashboard(self):
        return self.role in ('staff', 'admin')

    def can_assign_roles(self):
        return self.role == 'admin'

    def to_dict(self):
        """Return a safe JSON-serializable representation of the user."""
        return {
            'id':              self.id,
            'email':           self.email,
            'display_name':    self.display_name,
            'role':            self.role,
            'neighborhood_id': self.neighborhood_id,
            'is_active':       self.is_active,
            'created_at':      self.created_at.isoformat(),
            'bio':             self.bio,
            'avatar_url':      self.avatar_url,
            'phone':           self.phone,
        }

    def __repr__(self):
        return f'<User {self.email} [{self.role}]>'
