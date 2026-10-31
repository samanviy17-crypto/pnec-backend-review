# app/models/media.py
# Responsibility: MediaPost database model — uploaded photos/videos with captions.

from datetime import datetime
from app import db


class MediaPost(db.Model):
    """A photo or video uploaded by a coordinator or staff member."""

    __tablename__ = 'media_posts'

    id          = db.Column(db.Integer,    primary_key=True)
    title       = db.Column(db.String(200), nullable=False)
    caption     = db.Column(db.Text,        nullable=True)
    media_url   = db.Column(db.String(500), nullable=False)
    media_type  = db.Column(db.String(10),  nullable=False, default='image')  # 'image' | 'video'
    uploaded_by = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)
    event_id    = db.Column(db.Integer,    db.ForeignKey('events.id'), nullable=True)
    created_at  = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow)

    uploader = db.relationship('User',  back_populates='media_posts', foreign_keys=[uploaded_by])
    event    = db.relationship('Event', foreign_keys=[event_id])

    def to_dict(self):
        return {
            'id':            self.id,
            'title':         self.title,
            'caption':       self.caption,
            'media_url':     self.media_url,
            'media_type':    self.media_type,
            'uploaded_by':   self.uploaded_by,
            'uploader_name': self.uploader.display_name if self.uploader else 'PNEC',
            'event_id':      self.event_id,
            'created_at':    self.created_at.isoformat(),
        }

    def __repr__(self):
        return f'<MediaPost {self.id}: {self.title}>'
