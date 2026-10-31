# app/models/event.py
# Responsibility: Event database model — community events with date, location, and creator.

from datetime import datetime
from app import db


class Event(db.Model):
    """A PNEC community event (training, meeting, drill, etc.)."""

    __tablename__ = 'events'

    id          = db.Column(db.Integer,    primary_key=True)
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text,        nullable=True)
    date        = db.Column(db.DateTime,    nullable=False)
    location    = db.Column(db.String(200), nullable=True)
    image_url   = db.Column(db.String(500), nullable=True)
    created_by  = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)
    created_at  = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow)

    creator = db.relationship('User', back_populates='events_created', foreign_keys=[created_by])

    def to_dict(self):
        return {
            'id':          self.id,
            'title':       self.title,
            'description': self.description,
            'date':        self.date.isoformat(),
            'location':    self.location,
            'image_url':   self.image_url,
            'created_by':  self.created_by,
            'created_at':  self.created_at.isoformat(),
        }

    def __repr__(self):
        return f'<Event {self.id}: {self.title}>'
