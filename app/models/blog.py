from datetime import datetime
from app import db


class BlogPost(db.Model):
    __tablename__ = 'blog_posts'

    id              = db.Column(db.Integer, primary_key=True)
    title           = db.Column(db.String(255), nullable=False)
    slug            = db.Column(db.String(255), unique=True, nullable=False, index=True)
    content         = db.Column(db.Text, nullable=False, default='')
    excerpt         = db.Column(db.String(500), nullable=True)
    cover_image_url = db.Column(db.String(500), nullable=True)
    author_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    published       = db.Column(db.Boolean, default=False, nullable=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship('User', backref='blog_posts', lazy=True)

    def to_dict(self, include_content=True):
        d = {
            'id':              self.id,
            'title':           self.title,
            'slug':            self.slug,
            'excerpt':         self.excerpt,
            'cover_image_url': self.cover_image_url,
            'author_id':       self.author_id,
            'author_name':     self.author.display_name if self.author else None,
            'published':       self.published,
            'created_at':      self.created_at.isoformat() if self.created_at else None,
            'updated_at':      self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_content:
            d['content'] = self.content
        return d
