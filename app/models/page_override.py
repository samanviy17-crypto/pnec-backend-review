# app/models/page_override.py
# Responsibility: Stores per-element content overrides for any page.
# Each override is keyed by page_slug + element_id (Elementor data-id or custom key).

from datetime import datetime
from app import db


class PageOverride(db.Model):
    __tablename__ = 'page_overrides'
    __table_args__ = (
        db.UniqueConstraint('page_slug', 'element_id', name='uq_page_element'),
    )

    id         = db.Column(db.Integer,    primary_key=True)
    page_slug  = db.Column(db.String(80), nullable=False, index=True)
    element_id = db.Column(db.String(80), nullable=False)
    content    = db.Column(db.Text,       nullable=False, default='')
    updated_at = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)

    def to_dict(self):
        return {
            'id':         self.id,
            'page_slug':  self.page_slug,
            'element_id': self.element_id,
            'content':    self.content,
            'updated_at': self.updated_at.isoformat(),
        }
