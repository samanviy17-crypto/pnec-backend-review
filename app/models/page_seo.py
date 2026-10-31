# app/models/page_seo.py
# Responsibility: SEO metadata per page (title, description, og:image,
# canonical URL, robots). Stored separately from PageTemplate because
# SEO doesn't depend on the section list and is published independently.

from datetime import datetime
from app import db


SEO_FIELDS = (
    'title', 'description', 'og_image_url', 'og_title', 'og_description',
    'twitter_card', 'canonical_url', 'robots',
)
DEFAULT_SEO = {
    'title':           '',
    'description':     '',
    'og_image_url':    '',
    'og_title':        '',
    'og_description':  '',
    'twitter_card':    'summary_large_image',
    'canonical_url':   '',
    'robots':          'index, follow',
}


class PageSeo(db.Model):
    __tablename__ = 'page_seo'
    __table_args__ = (db.UniqueConstraint('page_slug', name='uq_page_seo_slug'),)

    id              = db.Column(db.Integer,    primary_key=True)
    page_slug       = db.Column(db.String(80), unique=True, nullable=False, index=True)
    title           = db.Column(db.String(200), nullable=True)
    description     = db.Column(db.String(400), nullable=True)
    og_image_url    = db.Column(db.String(500), nullable=True)
    og_title        = db.Column(db.String(200), nullable=True)
    og_description  = db.Column(db.String(400), nullable=True)
    twitter_card    = db.Column(db.String(40),  nullable=True, default='summary_large_image')
    canonical_url   = db.Column(db.String(500), nullable=True)
    robots          = db.Column(db.String(80),  nullable=True, default='index, follow')
    updated_at      = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow,
                                onupdate=datetime.utcnow)
    updated_by      = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)

    def to_dict(self):
        d = dict(DEFAULT_SEO)
        for k in SEO_FIELDS:
            v = getattr(self, k, None)
            if v is not None:
                d[k] = v
        d['page_slug']  = self.page_slug
        d['updated_at'] = self.updated_at.isoformat() if self.updated_at else None
        return d
