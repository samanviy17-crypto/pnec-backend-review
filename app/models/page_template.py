# app/models/page_template.py
# Responsibility: Per-page section/block composition for the v2 CMS editor.
# Each (page_slug, state) row holds a JSON template describing which sections
# the page renders, in what order, with what settings.

import json
from datetime import datetime
from app import db


# Allowed values for the `state` column.
STATE_DRAFT     = 'draft'
STATE_PUBLISHED = 'published'
VALID_STATES    = (STATE_DRAFT, STATE_PUBLISHED)


class PageTemplate(db.Model):
    """A composition of sections + blocks for a given page in a given state.

    template_json shape (stored as text, parsed via get_template / set_template):
    {
      "sections": {
        "<sid>": {
          "type": "hero",
          "settings": {"headline": "...", ...},
          "visible": true,
          "blocks": {"<bid>": {"type": "item", "settings": {...}}},
          "block_order": ["<bid>", ...]
        }
      },
      "order": ["<sid>", "<sid>", ...]
    }
    """

    __tablename__ = 'page_templates'
    __table_args__ = (
        db.UniqueConstraint('page_slug', 'state', name='uq_page_state'),
    )

    id            = db.Column(db.Integer,    primary_key=True)
    page_slug     = db.Column(db.String(80), nullable=False, index=True)
    state         = db.Column(db.String(16), nullable=False)
    template_json = db.Column(db.Text,       nullable=False, default='{"sections":{},"order":[]}')
    updated_at    = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow,
                              onupdate=datetime.utcnow)
    updated_by    = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)
    published_at  = db.Column(db.DateTime,   nullable=True)
    published_by  = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def get_template(self):
        """Parse template_json into a dict. Returns empty skeleton on failure."""
        try:
            d = json.loads(self.template_json) if self.template_json else {}
        except (ValueError, TypeError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault('sections', {})
        d.setdefault('order', [])
        return d

    def set_template(self, data):
        """Serialize a template dict back to JSON."""
        self.template_json = json.dumps(data or {'sections': {}, 'order': []})

    def to_dict(self):
        return {
            'id':            self.id,
            'page_slug':     self.page_slug,
            'state':         self.state,
            'template':      self.get_template(),
            'updated_at':    self.updated_at.isoformat() if self.updated_at else None,
            'updated_by':    self.updated_by,
            'published_at':  self.published_at.isoformat() if self.published_at else None,
            'published_by':  self.published_by,
        }
