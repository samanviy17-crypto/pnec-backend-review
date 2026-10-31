# app/models/chat.py
import json
from datetime import datetime
from app import db


class ChatSession(db.Model):
    __tablename__ = 'chat_sessions'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title      = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship('ChatMessage', back_populates='session',
                               cascade='all, delete-orphan', order_by='ChatMessage.created_at')
    user     = db.relationship('User', backref=db.backref('chat_sessions', lazy='dynamic',
                               cascade='all, delete-orphan'))

    def to_dict(self, include_preview=False):
        d = {
            'id':            self.id,
            'title':         self.title or f'Chat {self.id}',
            'created_at':    self.created_at.isoformat(),
            'updated_at':    self.updated_at.isoformat(),
            'message_count': len(self.messages),
        }
        if include_preview and self.messages:
            first_user = next((m for m in self.messages if m.role == 'user'), None)
            if first_user:
                d['preview'] = first_user.content[:120]
        return d


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'

    id         = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('chat_sessions.id'), nullable=False, index=True)
    role       = db.Column(db.String(20),  nullable=False)   # 'user' or 'assistant'
    content    = db.Column(db.Text,        nullable=False)
    image_url  = db.Column(db.Text,        nullable=True)
    created_at = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)

    session = db.relationship('ChatSession', back_populates='messages')

    def to_dict(self):
        return {
            'id':         self.id,
            'session_id': self.session_id,
            'role':       self.role,
            'content':    self.content,
            'image_url':  self.image_url,
            'created_at': self.created_at.isoformat(),
        }


class ChatUserMemory(db.Model):
    __tablename__ = 'chat_user_memories'

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True, index=True)
    memory_json = db.Column(db.Text, nullable=False, default='{}')
    updated_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('chat_memory', uselist=False,
                           cascade='all, delete-orphan'))

    def get(self):
        try:
            return json.loads(self.memory_json)
        except Exception:
            return {}

    def set(self, data):
        self.memory_json = json.dumps(data)
