# app/models/announcement.py
# Responsibility: Sitewide announcement/alert banner — admin posts, every page reads.

from datetime import datetime
from app import db

VALID_LEVELS = ('info', 'warning', 'danger')


class Announcement(db.Model):
    """A sitewide banner message visible to all visitors."""

    __tablename__ = 'announcements'

    id         = db.Column(db.Integer,   primary_key=True)
    message    = db.Column(db.Text,      nullable=False)
    level      = db.Column(db.String(20), nullable=False, default='info')   # info | warning | danger
    is_active  = db.Column(db.Boolean,   nullable=False, default=True)
    expires_at = db.Column(db.DateTime,  nullable=True)
    created_by = db.Column(db.Integer,   db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime,  nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime,  nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def is_expired(self):
        return self.expires_at is not None and datetime.utcnow() > self.expires_at

    def to_dict(self):
        return {
            'id':         self.id,
            'message':    self.message,
            'level':      self.level,
            'is_active':  self.is_active,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
