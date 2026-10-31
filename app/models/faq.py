# app/models/faq.py
# Responsibility: FAQ category and item models, plus user-submitted question model.

from datetime import datetime
from app import db


class FaqCategory(db.Model):
    """Groups of related FAQ questions (e.g. Wildfire, Earthquake)."""

    __tablename__ = 'faq_categories'

    id            = db.Column(db.Integer,    primary_key=True)
    name          = db.Column(db.String(80), nullable=False)
    icon          = db.Column(db.String(10), nullable=True)   # emoji
    display_order = db.Column(db.Integer,    nullable=False, default=0)

    items = db.relationship('FaqItem', back_populates='category',
                            order_by='FaqItem.id', lazy='dynamic')

    def to_dict(self):
        return {
            'id':            self.id,
            'name':          self.name,
            'icon':          self.icon,
            'display_order': self.display_order,
        }

    def __repr__(self):
        return f'<FaqCategory {self.name}>'


class FaqItem(db.Model):
    """A single FAQ question-answer pair belonging to a category."""

    __tablename__ = 'faq_items'

    id            = db.Column(db.Integer,    primary_key=True)
    category_id   = db.Column(db.Integer,    db.ForeignKey('faq_categories.id'), nullable=False)
    question      = db.Column(db.String(255), nullable=False)
    answer        = db.Column(db.Text,        nullable=False)
    helpful_count = db.Column(db.Integer,     nullable=False, default=0)
    created_at    = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)

    category = db.relationship('FaqCategory', back_populates='items')

    def to_dict(self):
        return {
            'id':            self.id,
            'category_id':   self.category_id,
            'question':      self.question,
            'answer':        self.answer,
            'helpful_count': self.helpful_count,
        }

    def __repr__(self):
        return f'<FaqItem {self.id}: {self.question[:40]}>'


class UserQuestion(db.Model):
    """A question submitted by a resident, awaiting staff response."""

    __tablename__ = 'user_questions'

    STATUS_OPEN      = 'open'
    STATUS_CLAIMED   = 'claimed'
    STATUS_ANSWERED  = 'answered'

    id                  = db.Column(db.Integer,    primary_key=True)
    user_id             = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)
    display_name        = db.Column(db.String(100), nullable=False)
    email               = db.Column(db.String(255), nullable=False)
    question_text       = db.Column(db.Text,        nullable=False)
    status              = db.Column(db.String(20),  nullable=False, default='open')
    claimed_by_staff_id = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)
    answer_text         = db.Column(db.Text,        nullable=True)
    created_at          = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow)
    answered_at         = db.Column(db.DateTime,   nullable=True)

    submitter    = db.relationship('User', foreign_keys=[user_id])
    claimed_by   = db.relationship('User', foreign_keys=[claimed_by_staff_id])

    def to_dict(self):
        return {
            'id':                  self.id,
            'display_name':        self.display_name,
            'email':               self.email,
            'question_text':       self.question_text,
            'status':              self.status,
            'claimed_by_staff_id': self.claimed_by_staff_id,
            'claimed_by_name':     self.claimed_by.display_name if self.claimed_by else None,
            'answer_text':         self.answer_text,
            'created_at':          self.created_at.isoformat(),
            'answered_at':         self.answered_at.isoformat() if self.answered_at else None,
        }

    def __repr__(self):
        return f'<UserQuestion {self.id} [{self.status}]>'


class FaqFeedback(db.Model):
    """One changeable vote per FAQ and account/browser session."""
    __tablename__ = 'faq_feedback'
    item_id = db.Column(db.Integer, db.ForeignKey('faq_items.id'), primary_key=True)
    voter_key = db.Column(db.String(80), primary_key=True)
    helpful = db.Column(db.Boolean, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
