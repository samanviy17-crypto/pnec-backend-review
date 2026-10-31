# app/models/site_config.py
# Responsibility: Editable site-wide key/value configuration managed by admins.

from datetime import datetime
from app import db


class SiteConfig(db.Model):
    """A single editable key/value pair for site-wide configuration."""

    __tablename__ = 'site_config'

    id         = db.Column(db.Integer,    primary_key=True)
    key        = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value      = db.Column(db.Text,       nullable=False, default='')
    label      = db.Column(db.String(120), nullable=False)
    description= db.Column(db.String(255), nullable=True)
    group      = db.Column(db.String(60),  nullable=False, default='general')
    updated_at = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)

    def to_dict(self):
        return {
            'id':          self.id,
            'key':         self.key,
            'value':       self.value,
            'label':       self.label,
            'description': self.description,
            'group':       self.group,
            'updated_at':  self.updated_at.isoformat(),
        }
