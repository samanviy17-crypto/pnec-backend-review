# app/models/push_subscription.py
from datetime import datetime
from app import db


class PushSubscription(db.Model):
    __tablename__ = 'push_subscriptions'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    endpoint   = db.Column(db.Text, nullable=False, unique=True)
    p256dh     = db.Column(db.Text, nullable=False)
    auth       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_used  = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('push_subscriptions', lazy='dynamic'))

    def to_dict(self):
        return {
            'id':         self.id,
            'endpoint':   self.endpoint,
            'created_at': self.created_at.isoformat(),
        }
