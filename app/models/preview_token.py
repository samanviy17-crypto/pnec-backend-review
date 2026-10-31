# app/models/preview_token.py
# Responsibility: Time-limited tokens that grant non-admin users read-only
# access to a page's draft state via ?preview=1&token=...

import secrets
from datetime import datetime, timedelta
from app import db


# Default lifetime if caller does not specify
DEFAULT_TOKEN_TTL_DAYS = 7


class PreviewToken(db.Model):
    """A short-lived token that lets anyone read a specific page's draft."""

    __tablename__ = 'preview_tokens'

    id         = db.Column(db.Integer,    primary_key=True)
    token      = db.Column(db.String(64), unique=True, nullable=False, index=True)
    page_slug  = db.Column(db.String(80), nullable=False)
    expires_at = db.Column(db.DateTime,   nullable=False)
    created_by = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow)

    @classmethod
    def issue(cls, page_slug, created_by=None, ttl_days=DEFAULT_TOKEN_TTL_DAYS):
        """Create and return a new token (caller must commit)."""
        return cls(
            token=secrets.token_urlsafe(32),
            page_slug=page_slug,
            expires_at=datetime.utcnow() + timedelta(days=ttl_days),
            created_by=created_by,
        )

    def is_valid_for(self, page_slug):
        return (self.page_slug == page_slug
                and self.expires_at > datetime.utcnow())

    def to_dict(self):
        return {
            'token':      self.token,
            'page_slug':  self.page_slug,
            'expires_at': self.expires_at.isoformat(),
            'created_at': self.created_at.isoformat(),
        }
