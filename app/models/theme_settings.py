# app/models/theme_settings.py
# Responsibility: Site-wide theme tokens (colors, fonts, logo, spacing) that
# all CMS sections reference via CSS custom properties. Stored as a single
# JSON blob per state (draft/published) so the editor can change everything
# atomically and roll back on Discard.

import json
from datetime import datetime
from app import db


# Allowed values for the `state` column.
STATE_DRAFT     = 'draft'
STATE_PUBLISHED = 'published'
VALID_STATES    = (STATE_DRAFT, STATE_PUBLISHED)


# Default tokens shipped on first run. Editor presents these as the canonical
# list; admins override values but cannot add/remove keys (that requires a
# code change here so it's reviewable).
DEFAULT_TOKENS = {
    # Color scheme — `primary` is the "PNEC navy", `accent` is amber.
    'color_primary':         '#1e3a8a',
    'color_primary_text':    '#ffffff',
    'color_accent':          '#f59e0b',
    'color_accent_text':     '#1f2937',
    'color_background':      '#ffffff',
    'color_text':            '#1e293b',
    'color_muted':           '#64748b',
    'color_alert_red':       '#dc2626',
    'color_alert_amber':     '#f59e0b',
    'color_alert_green':     '#10b981',
    # Typography
    'font_heading':          'system-ui, -apple-system, sans-serif',
    'font_body':             'system-ui, -apple-system, sans-serif',
    'font_size_base':        '16px',
    'font_weight_heading':   '700',
    # Layout
    'radius_md':             '6px',
    'radius_lg':             '12px',
    'spacing_section_y':     '48px',
    'max_width_content':     '1080px',
    # Brand
    'logo_url':              '',
    'site_name':             'Poway Neighborhood Emergency Corps',
    # Named color schemes (Shopify-style: sections reference these by name)
    'scheme_1_bg':           '#ffffff',
    'scheme_1_text':         '#1e293b',
    'scheme_2_bg':           '#1e3a8a',
    'scheme_2_text':         '#ffffff',
    'scheme_3_bg':           '#f59e0b',
    'scheme_3_text':         '#1f2937',
    'scheme_4_bg':           '#dc2626',
    'scheme_4_text':         '#ffffff',
}


# Display metadata for the editor UI. Keeping this here keeps the editor
# automatic — fields render from the dict, no manual form.
TOKEN_META = {
    'color_primary':       {'label': 'Primary color',         'type': 'color',  'group': 'colors'},
    'color_primary_text':  {'label': 'Primary text color',    'type': 'color',  'group': 'colors'},
    'color_accent':        {'label': 'Accent color',          'type': 'color',  'group': 'colors'},
    'color_accent_text':   {'label': 'Accent text color',     'type': 'color',  'group': 'colors'},
    'color_background':    {'label': 'Page background',       'type': 'color',  'group': 'colors'},
    'color_text':          {'label': 'Body text color',       'type': 'color',  'group': 'colors'},
    'color_muted':         {'label': 'Muted text color',      'type': 'color',  'group': 'colors'},
    'color_alert_red':     {'label': 'Alert — red',           'type': 'color',  'group': 'colors'},
    'color_alert_amber':   {'label': 'Alert — amber',         'type': 'color',  'group': 'colors'},
    'color_alert_green':   {'label': 'Alert — green',         'type': 'color',  'group': 'colors'},
    'font_heading':        {'label': 'Heading font stack',    'type': 'text',   'group': 'typography'},
    'font_body':           {'label': 'Body font stack',       'type': 'text',   'group': 'typography'},
    'font_size_base':      {'label': 'Base font size',        'type': 'text',   'group': 'typography'},
    'font_weight_heading': {'label': 'Heading font weight',   'type': 'select', 'group': 'typography',
                            'options': ['400', '500', '600', '700', '800']},
    'radius_md':           {'label': 'Medium border radius',  'type': 'text',   'group': 'layout'},
    'radius_lg':           {'label': 'Large border radius',   'type': 'text',   'group': 'layout'},
    'spacing_section_y':   {'label': 'Section vertical pad',  'type': 'text',   'group': 'layout'},
    'max_width_content':   {'label': 'Content max width',     'type': 'text',   'group': 'layout'},
    'logo_url':            {'label': 'Logo image',            'type': 'image',  'group': 'brand'},
    'site_name':           {'label': 'Site name',             'type': 'text',   'group': 'brand'},
    'scheme_1_bg':         {'label': 'Scheme 1 — Background', 'type': 'color',  'group': 'schemes'},
    'scheme_1_text':       {'label': 'Scheme 1 — Text',       'type': 'color',  'group': 'schemes'},
    'scheme_2_bg':         {'label': 'Scheme 2 — Background', 'type': 'color',  'group': 'schemes'},
    'scheme_2_text':       {'label': 'Scheme 2 — Text',       'type': 'color',  'group': 'schemes'},
    'scheme_3_bg':         {'label': 'Scheme 3 — Background', 'type': 'color',  'group': 'schemes'},
    'scheme_3_text':       {'label': 'Scheme 3 — Text',       'type': 'color',  'group': 'schemes'},
    'scheme_4_bg':         {'label': 'Scheme 4 — Background', 'type': 'color',  'group': 'schemes'},
    'scheme_4_text':       {'label': 'Scheme 4 — Text',       'type': 'color',  'group': 'schemes'},
}


class ThemeSettings(db.Model):
    """A theme tokens snapshot in either draft or published state."""

    __tablename__ = 'theme_settings'
    __table_args__ = (db.UniqueConstraint('state', name='uq_theme_state'),)

    id           = db.Column(db.Integer,    primary_key=True)
    state        = db.Column(db.String(16), nullable=False)
    tokens_json  = db.Column(db.Text,       nullable=False, default=json.dumps(DEFAULT_TOKENS))
    updated_at   = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow,
                             onupdate=datetime.utcnow)
    updated_by   = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)
    published_at = db.Column(db.DateTime,   nullable=True)
    published_by = db.Column(db.Integer,    db.ForeignKey('users.id'), nullable=True)

    def get_tokens(self):
        """Parse tokens_json + merge defaults so missing keys fall back to default."""
        try:
            saved = json.loads(self.tokens_json) if self.tokens_json else {}
        except (ValueError, TypeError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        merged = dict(DEFAULT_TOKENS)
        for k, v in saved.items():
            if k in DEFAULT_TOKENS:
                merged[k] = v
        return merged

    def set_tokens(self, data):
        merged = dict(DEFAULT_TOKENS)
        for k, v in (data or {}).items():
            if k in DEFAULT_TOKENS:
                merged[k] = v
        self.tokens_json = json.dumps(merged)

    def to_dict(self):
        return {
            'state':        self.state,
            'tokens':       self.get_tokens(),
            'updated_at':   self.updated_at.isoformat() if self.updated_at else None,
            'published_at': self.published_at.isoformat() if self.published_at else None,
        }


def tokens_to_css(tokens):
    """Render a token dict to a `:root { --token: value; ... }` CSS string.

    BUG FIX (v2.40): the previous escape only handled quotes and backslashes
    but left ; { } < through. A malicious admin could plant a CSS injection
    payload like 'red; color: blue' and break out of the property — affecting
    every page on the site. We now also strip those structural characters
    AND drop tokens whose value contains URL/expression hooks. Admins are
    generally trusted but defense-in-depth on a global stylesheet is cheap.
    """
    parts = [':root {']
    for k, v in tokens.items():
        css_var = '--cms-' + k.replace('_', '-')
        s = str(v)
        # Defensive sanitization — strip CSS structural chars and < to defeat
        # css/html injection. Keeps standard property values intact (hex, rgb(),
        # var(--…), 16px, 1.4rem, etc.).
        for bad in (';', '{', '}', '<', '>'):
            s = s.replace(bad, '')
        # Block CSS expression() / behavior: / -moz-binding hooks (legacy IE
        # vectors but still). These would only matter on very old browsers,
        # but cheap to block.
        low = s.lower()
        if any(needle in low for needle in ('expression(', 'behavior:', '-moz-binding', 'javascript:', 'url(javascript')):
            continue
        # Escape single quotes / backslashes
        safe = s.replace('\\', '\\\\').replace("'", "\\'")
        parts.append(f'  {css_var}: {safe};')
    parts.append('}')
    return '\n'.join(parts)
