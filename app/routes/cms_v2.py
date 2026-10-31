# app/routes/cms_v2.py
# Responsibility: v2 CMS API — page-level section/block composition with
# draft/publish workflow. Public read of the published state, admin (or
# preview-token) read of the draft, admin-only writes.
#
# Endpoints (all under /api):
#   GET    /cms/sections-registry          List available section types + schemas
#   GET    /cms/page/<slug>                Read a page (state=published default)
#   GET    /cms/page/<slug>/draft          Convenience for draft-state read
#   PATCH  /cms/page/<slug>/draft          Apply a list of patches to the draft
#   POST   /cms/page/<slug>/publish        Copy draft → published
#   GET    /cms/render                     Render a single section to HTML
#   POST   /cms/page/<slug>/preview-token  Issue a 7-day share-preview token

import json
import secrets
from datetime import datetime
from copy import deepcopy

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app import db
from app.models.page_template import PageTemplate, STATE_DRAFT, STATE_PUBLISHED, VALID_STATES
from app.models.page_template_revision import PageTemplateRevision, record_revision
from app.models.preview_token import PreviewToken
from app.models.page_seo import PageSeo, SEO_FIELDS, DEFAULT_SEO
from app.services.cms_renderer import render_page, render_section
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role


cms_v2_bp = Blueprint('cms_v2', __name__)


# Soft enforcement matching Shopify's limit. Caller can disable via DEBUG flag.
MAX_SECTIONS_PER_PAGE = 25
MAX_BLOCKS_PER_SECTION = 50

# Allowed characters in a page slug. Mirrors the URL-safe slug shape every
# other CMS uses: lowercase letters, digits, hyphens. Length 1-80. Underscore
# permitted as the leading char only (for canonical groups like _header).
import re as _re
_SLUG_RE = _re.compile(r'^_?[a-z0-9]+(?:-[a-z0-9]+)*$')

def _valid_slug(s):
    if not isinstance(s, str): return False
    s = s.strip()
    if not s or len(s) > 80: return False
    return bool(_SLUG_RE.match(s))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _registry():
    """Pull the registry instance off the Flask app."""
    return current_app.config.get('CMS_REGISTRY')


def _get_or_create_template(page_slug, state):
    """Return the PageTemplate row for this (slug, state). Creates an empty
    draft on demand. Published rows are NOT auto-created (caller publishes)."""
    row = PageTemplate.query.filter_by(page_slug=page_slug, state=state).first()
    if row:
        return row
    if state == STATE_DRAFT:
        row = PageTemplate(
            page_slug=page_slug,
            state=STATE_DRAFT,
            template_json='{"sections":{},"order":[]}',
        )
        db.session.add(row)
        db.session.commit()
        return row
    return None


def _sid():
    """Generate a stable section/block id (URL-safe, 12 chars)."""
    return secrets.token_urlsafe(8)[:12].replace('-', 'a').replace('_', 'b')


def _is_admin():
    return (current_user.is_authenticated
            and getattr(current_user, 'role', None) == 'admin')


def _check_token(page_slug, token):
    """Return True if token grants read access to this page's draft."""
    if not token:
        return False
    row = PreviewToken.query.filter_by(token=token).first()
    return bool(row and row.is_valid_for(page_slug))


# ─── Pages list ──────────────────────────────────────────────────────────────

@cms_v2_bp.route('/cms/pages', methods=['GET'])
def list_pages():
    """Return the list of pages that have any v2 template (draft or published).
    Public — used by the editor to populate its page selector."""
    rows = (PageTemplate.query
            .with_entities(PageTemplate.page_slug, PageTemplate.state, PageTemplate.updated_at)
            .all())
    by_slug = {}
    for slug, state, updated_at in rows:
        entry = by_slug.setdefault(slug, {'page_slug': slug, 'has_draft': False,
                                          'has_published': False, 'updated_at': None})
        if state == STATE_DRAFT:     entry['has_draft']     = True
        if state == STATE_PUBLISHED: entry['has_published'] = True
        if updated_at and (not entry['updated_at'] or updated_at > entry['updated_at']):
            entry['updated_at'] = updated_at
    pages = sorted(by_slug.values(), key=lambda p: p['page_slug'])
    # Always include the canonical built-in pages + header/footer section
    # groups even if empty
    seen = {p['page_slug'] for p in pages}
    for canon in ('home', 'about', 'programs', '_header', '_footer'):
        if canon not in seen:
            pages.append({'page_slug': canon, 'has_draft': False,
                          'has_published': False, 'updated_at': None})
    # ISO-format timestamps
    for p in pages:
        p['updated_at'] = p['updated_at'].isoformat() if p['updated_at'] else None
    return jsonify({'pages': pages}), 200


# ─── Cross-page section search ───────────────────────────────────────────────

@cms_v2_bp.route('/cms/search', methods=['GET'])
@requires_role('admin')
def search_sections():
    """Find every editable thing across the site that matches a query.

    v3 (Phase 1): now searches sections AND site-config keys AND
    page-overrides AND theme tokens, so admins can find e.g. the footer
    copyright text (which lives in site_config, not in any section).

    Query params:
      q:     text to search (case-insensitive, substring)
      type:  filter to one section type (sections only)
      state: 'draft' (default) | 'published' (sections + theme only)
      kinds: comma-separated subset of {section, override, site_config, theme}
             — defaults to all four
    """
    from app.models.site_config import SiteConfig
    from app.models.page_override import PageOverride
    from app.models.theme_settings import ThemeSettings

    q = (request.args.get('q') or '').strip().lower()
    type_filter = (request.args.get('type') or '').strip()
    state = (request.args.get('state') or STATE_DRAFT).strip()
    if state not in VALID_STATES:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'invalid state'})
    kinds = set(((request.args.get('kinds') or 'section,override,site_config,theme')
                 .split(',')))

    hits = []

    # Sections (existing behavior)
    if 'section' in kinds:
        rows = PageTemplate.query.filter_by(state=state).all()
        for row in rows:
            tpl = row.get_template()
            for sid, sec in (tpl.get('sections') or {}).items():
                if type_filter and sec.get('type') != type_filter:
                    continue
                if q:
                    blob = (json.dumps(sec.get('settings') or {}, default=str).lower()
                            + json.dumps(sec.get('blocks') or {}, default=str).lower()
                            + (sec.get('name') or '').lower()
                            + (sec.get('type') or '').lower())
                    if q not in blob:
                        continue
                hits.append({
                    'kind':      'section',
                    'page_slug': row.page_slug,
                    'sid':       sid,
                    'type':      sec.get('type'),
                    'name':      sec.get('name'),
                    'preview':   _preview_blurb(sec),
                })

    # Site-config keys (footer copyright, brand name, nav labels, etc.)
    if 'site_config' in kinds and not type_filter:
        for cfg in SiteConfig.query.all():
            v = cfg.value if isinstance(cfg.value, str) else json.dumps(cfg.value or '', default=str)
            if q and q not in (cfg.key.lower() + ' ' + v.lower()):
                continue
            hits.append({
                'kind':      'site_config',
                'cfg_key':   cfg.key,
                'preview':   (v or '')[:120],
                'name':      cfg.key,
            })

    # Page overrides (per-page text/url overrides via data-cms-override)
    if 'override' in kinds and not type_filter:
        for ov in PageOverride.query.all():
            v = ov.value if isinstance(ov.value, str) else json.dumps(ov.value or '', default=str)
            if q and q not in (
                (ov.element_id or '').lower() + ' ' + (ov.page_slug or '').lower() + ' ' + v.lower()
            ):
                continue
            hits.append({
                'kind':       'override',
                'page_slug':  ov.page_slug,
                'element_id': ov.element_id,
                'preview':    (v or '')[:120],
                'name':       ov.element_id,
            })

    # Theme tokens (color hex, font names, etc.)
    if 'theme' in kinds and not type_filter:
        theme = ThemeSettings.query.filter_by(state=state).first()
        if theme:
            tokens = theme.tokens or {}
            for k, v in tokens.items():
                vs = v if isinstance(v, str) else json.dumps(v, default=str)
                if q and q not in (k.lower() + ' ' + vs.lower()):
                    continue
                hits.append({
                    'kind':     'theme',
                    'cfg_key':  k,
                    'preview':  (vs or '')[:120],
                    'name':     k,
                })

    return jsonify({'hits': hits[:300], 'count': len(hits)}), 200


def _preview_blurb(section):
    """Build a short human-friendly snippet for search results."""
    s = section.get('settings') or {}
    for key in ('headline', 'heading', 'title', 'message', 'sub_headline', 'body'):
        v = s.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:120]
    return (section.get('name') or section.get('type') or '')


def _summarize_op(patch, before, after):
    """Phase 2 helper: turn a single patch op into a one-line summary that
    reads well in the history panel."""
    op = (patch or {}).get('op', 'unknown')
    sid = (patch or {}).get('sid')
    if op == 'add':
        return f"Added {patch.get('type', 'section')}"
    if op == 'remove':
        section = (before.get('sections') or {}).get(sid) or {}
        return f"Removed {section.get('type', 'section')}"
    if op == 'duplicate':
        return f"Duplicated section"
    if op == 'reorder':
        return f"Reordered sections"
    if op == 'set':
        return f"Updated {patch.get('key', 'field')}"
    if op == 'bulk_set':
        return f"Replaced section settings"
    if op == 'visibility':
        return f"{'Showed' if patch.get('visible') else 'Hid'} section"
    if op == 'rename':
        return f"Renamed to {(patch.get('name') or '').strip()[:40]}"
    if op == 'replace_template':
        return f"Replaced full page template"
    if op == 'add_block':
        return f"Added {patch.get('block_type', 'block')}"
    if op == 'remove_block':
        return f"Removed block"
    if op == 'reorder_blocks':
        return f"Reordered blocks"
    if op == 'set_block':
        return f"Updated block.{patch.get('key', 'field')}"
    if op == 'device_visibility':
        on = patch.get('on') or {}
        on_str = '+'.join(k for k, v in on.items() if v)
        return f"Visibility: {on_str or 'none'}"
    if op == 'layout':
        return f"Updated layout/spacing"
    return op


# ─── Audit log ───────────────────────────────────────────────────────────────

@cms_v2_bp.route('/cms/audit', methods=['GET'])
@requires_role('admin')
def get_audit_log():
    """Return recent template + theme + override changes, newest first.
    Optional: ?page=<slug> filters to a single page."""
    from app.models.theme_settings import ThemeSettings
    from app.models.page_override import PageOverride
    from app.models.user import User
    page_slug = request.args.get('page')
    limit = min(int(request.args.get('limit') or 50), 200)

    events = []
    # Page templates
    q = PageTemplate.query
    if page_slug:
        q = q.filter_by(page_slug=page_slug)
    for row in q.order_by(PageTemplate.updated_at.desc()).limit(limit).all():
        events.append({
            'kind':       'page_template',
            'page_slug':  row.page_slug,
            'state':      row.state,
            'updated_at': row.updated_at.isoformat() if row.updated_at else None,
            'updated_by': row.updated_by,
            'detail':     f'Edited {row.state} of {row.page_slug}',
        })
        if row.published_at:
            events.append({
                'kind':       'page_publish',
                'page_slug':  row.page_slug,
                'updated_at': row.published_at.isoformat(),
                'updated_by': row.published_by,
                'detail':     f'Published {row.page_slug}',
            })
    # Theme
    for row in ThemeSettings.query.order_by(ThemeSettings.updated_at.desc()).limit(limit).all():
        events.append({
            'kind':       'theme',
            'state':      row.state,
            'updated_at': row.updated_at.isoformat() if row.updated_at else None,
            'updated_by': row.updated_by,
            'detail':     f'Theme {row.state} updated',
        })
    # Overrides
    oq = PageOverride.query
    if page_slug:
        oq = oq.filter_by(page_slug=page_slug)
    for row in oq.order_by(PageOverride.updated_at.desc()).limit(limit).all():
        # Auto-tagged keys (auto__h1_xxx) are noisier — give them a friendlier
        # detail line.
        is_auto = (row.element_id or '').startswith('auto__')
        events.append({
            'kind':       'override',
            'page_slug':  row.page_slug,
            'element_id': row.element_id,
            'is_auto':    is_auto,
            'updated_at': row.updated_at.isoformat() if row.updated_at else None,
            'updated_by': row.updated_by,
            'detail':     f'Inline-edited "{row.element_id}" on {row.page_slug}'
                          if not is_auto else
                          f'Inline-edited text on {row.page_slug}',
        })

    # Site-config (cross-page settings — navbar/footer)
    from app.models.site_config import SiteConfig
    for row in SiteConfig.query.order_by(SiteConfig.updated_at.desc()).limit(limit).all():
        events.append({
            'kind':       'site_config',
            'cfg_key':    row.key,
            'updated_at': row.updated_at.isoformat() if row.updated_at else None,
            'updated_by': row.updated_by,
            'detail':     f'Site config "{row.key}" updated',
        })

    # Resolve user display names
    user_ids = [e['updated_by'] for e in events if e.get('updated_by')]
    users = {u.id: u.display_name or u.email
             for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    for e in events:
        e['updated_by_name'] = users.get(e.get('updated_by')) or 'unknown'

    events.sort(key=lambda e: e.get('updated_at') or '', reverse=True)
    return jsonify({'events': events[:limit]}), 200


# ─── Sections registry endpoint ──────────────────────────────────────────────

@cms_v2_bp.route('/cms/sections-registry', methods=['GET'])
def get_sections_registry():
    """Return the list of section types available to instantiate.
    Public: the editor needs this to render its picker, and hydrate.js may
    use it to pre-validate. No template source is exposed here."""
    reg = _registry()
    if not reg:
        return error_response('SERVER_ERROR', 500, {'detail': 'cms registry not initialized'})
    return jsonify({'sections': reg.list_types()}), 200


# ─── Page read endpoints ─────────────────────────────────────────────────────

@cms_v2_bp.route('/cms/page/<string:page_slug>', methods=['GET'])
def get_page(page_slug):
    """Read a page's template + rendered sections.

    Query params:
      state:  'published' (default) or 'draft'
      token:  preview token (only relevant when state=draft)
    """
    state = (request.args.get('state') or STATE_PUBLISHED).strip()
    if state not in VALID_STATES:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'invalid state'})

    if state == STATE_DRAFT:
        token = request.args.get('token')
        if not (_is_admin() or _check_token(page_slug, token)):
            return error_response('UNAUTHORIZED', 401)

    row = PageTemplate.query.filter_by(page_slug=page_slug, state=state).first()
    if not row:
        # Returning empty template is friendlier for the FE than 404 — the page
        # simply has no v2 sections yet, which is the expected state for new pages.
        return jsonify({
            'page_slug':     page_slug,
            'state':         state,
            'template':      {'sections': {}, 'order': []},
            'sections_html': {},
            'updated_at':    None,
        }), 200

    template = row.get_template()
    reg = _registry()
    sections_html = render_page(template, reg) if reg else {}
    return jsonify({
        'page_slug':     row.page_slug,
        'state':         row.state,
        'template':      template,
        'sections_html': sections_html,
        'updated_at':    row.updated_at.isoformat() if row.updated_at else None,
        'published_at':  row.published_at.isoformat() if row.published_at else None,
    }), 200


@cms_v2_bp.route('/cms/page/<string:page_slug>/draft', methods=['GET'])
@requires_role('admin')
def get_page_draft(page_slug):
    """Admin convenience: same as GET /cms/page/<slug>?state=draft.

    BUG FIX (v2.36): the previous implementation copied request.args to make
    it mutable but never ADDED `state=draft`, so this endpoint was actually
    returning the PUBLISHED template. The FE happens to call the query-param
    form (?state=draft) directly, so this didn't get caught — but anyone
    using the convenience endpoint got the wrong data silently.
    """
    args = request.args.copy()
    args['state'] = STATE_DRAFT
    request.args = args
    return get_page(page_slug)


# ─── Page write endpoint ─────────────────────────────────────────────────────

@cms_v2_bp.route('/cms/page/<string:page_slug>/draft', methods=['PATCH'])
@requires_role('admin')
def patch_page_draft(page_slug):
    """Apply a list of patches to the draft template.

    Body: { "patches": [ { "op": ..., ... }, ... ] }

    Supported ops:
      add       {op:'add',    sid?, type, settings?, index?}
      remove    {op:'remove', sid}
      duplicate {op:'duplicate', sid, new_sid?}
      reorder   {op:'reorder', order: [sid, sid, ...]}
      set       {op:'set',    sid, key, value}            update one setting
      bulk      {op:'bulk_set', sid, settings: {...}}     replace section settings
      visibility{op:'visibility', sid, visible: bool}
      add_block {op:'add_block', sid, block_type, settings?}
      remove_block {op:'remove_block', sid, bid}
      reorder_blocks {op:'reorder_blocks', sid, block_order: [bid, ...]}
      set_block {op:'set_block', sid, bid, key, value}

    Returns the updated template plus the rendered HTML for any sections that
    changed (so the editor can hot-swap exactly those).
    """
    data = request.get_json(silent=True) or {}
    patches = data.get('patches')
    if not isinstance(patches, list):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'patches must be a list'})

    row = _get_or_create_template(page_slug, STATE_DRAFT)
    template = row.get_template()
    # Phase 2: snapshot the BEFORE state so we can record a revision after
    # the patch loop completes (only if it actually changed something).
    pre_snapshot = deepcopy(template)
    reg = _registry()
    if not reg:
        return error_response('SERVER_ERROR', 500, {'detail': 'cms registry not initialized'})

    affected = set()  # sids whose rendered output should be returned

    for patch in patches:
        op = (patch or {}).get('op')
        if op == 'add':
            type_id = patch.get('type')
            if not type_id or not reg.get(type_id):
                return error_response('VALIDATION_FAILED', 400,
                                      {'detail': f'unknown section type {type_id!r}'})
            if len(template['order']) >= MAX_SECTIONS_PER_PAGE:
                return error_response('VALIDATION_FAILED', 400, {
                    'detail': f'page is at the {MAX_SECTIONS_PER_PAGE}-section limit; remove one before adding more.',
                })
            sid = patch.get('sid') or _sid()
            settings = patch.get('settings') or reg.default_settings(type_id)
            section_obj = {
                'type':        type_id,
                'settings':    settings,
                'visible':     True,
                'blocks':      {},
                'block_order': [],
            }
            # Inline blocks support — presets + AI use this for single round-trip
            for b in (patch.get('blocks') or []):
                bid = _sid()
                section_obj['blocks'][bid] = {
                    'type':     b.get('type') or 'item',
                    'settings': b.get('settings') or {},
                }
                section_obj['block_order'].append(bid)
            template['sections'][sid] = section_obj
            index = patch.get('index')
            if isinstance(index, int) and 0 <= index <= len(template['order']):
                template['order'].insert(index, sid)
            else:
                template['order'].append(sid)
            affected.add(sid)

        elif op == 'remove':
            sid = patch.get('sid')
            template['sections'].pop(sid, None)
            template['order'] = [x for x in template['order'] if x != sid]

        elif op == 'duplicate':
            sid = patch.get('sid')
            src = template['sections'].get(sid)
            if not src:
                continue
            # BUG FIX (v2.37): bulk_duplicate (v2.20) could let an admin blast
            # past 25 sections by duplicating multiple at once. The `add` op
            # checks the limit; `duplicate` should too.
            if len(template['order']) >= MAX_SECTIONS_PER_PAGE:
                return error_response('VALIDATION_FAILED', 400, {
                    'detail': f'page is at the {MAX_SECTIONS_PER_PAGE}-section limit; remove one before duplicating more.',
                })
            new_sid = patch.get('new_sid') or _sid()
            template['sections'][new_sid] = deepcopy(src)
            # Insert the duplicate immediately after the source in `order`
            try:
                idx = template['order'].index(sid)
                template['order'].insert(idx + 1, new_sid)
            except ValueError:
                template['order'].append(new_sid)
            affected.add(new_sid)

        elif op == 'reorder':
            new_order = patch.get('order')
            if not isinstance(new_order, list):
                return error_response('VALIDATION_FAILED', 400, {'detail': 'order must be a list'})
            # Only allow reordering of existing sids; drop unknowns silently
            known = set(template['sections'].keys())
            template['order'] = [x for x in new_order if x in known]

        elif op == 'set':
            sid = patch.get('sid')
            key = patch.get('key')
            section = template['sections'].get(sid)
            if section is None or not key:
                continue
            section.setdefault('settings', {})
            section['settings'][key] = patch.get('value')
            affected.add(sid)

        elif op == 'bulk_set':
            sid = patch.get('sid')
            section = template['sections'].get(sid)
            if section is None:
                continue
            section['settings'] = patch.get('settings') or {}
            affected.add(sid)

        elif op == 'visibility':
            sid = patch.get('sid')
            section = template['sections'].get(sid)
            if section is None:
                continue
            section['visible'] = bool(patch.get('visible', True))
            affected.add(sid)

        elif op == 'rename':
            sid = patch.get('sid')
            section = template['sections'].get(sid)
            if section is None:
                continue
            name = (patch.get('name') or '').strip()[:120]
            if name:
                section['name'] = name
            else:
                section.pop('name', None)
            affected.add(sid)

        elif op == 'replace_template':
            # Wholesale replace the draft template (used by undo/redo).
            new_t = patch.get('template') or {}
            if not isinstance(new_t, dict):
                return error_response('VALIDATION_FAILED', 400, {'detail': 'template must be an object'})
            new_t.setdefault('sections', {})
            new_t.setdefault('order', [])
            template['sections'] = new_t['sections']
            template['order']    = new_t['order']
            affected.update(new_t['sections'].keys())

        elif op == 'device_visibility':
            sid = patch.get('sid')
            section = template['sections'].get(sid)
            if section is None:
                continue
            devices = patch.get('devices') or ['desktop', 'tablet', 'mobile']
            allowed = {'desktop', 'tablet', 'mobile'}
            section['device_visibility'] = [d for d in devices if d in allowed]
            affected.add(sid)

        elif op == 'layout':
            sid = patch.get('sid')
            section = template['sections'].get(sid)
            if section is None:
                continue
            section.setdefault('layout', {})
            # BUG FIX (v2.40): `animation` was missing from this allowlist, so
            # the per-section entrance animation feature shipped in v2.25
            # silently dropped its value on every save. Added.
            ALLOWED_LAYOUT = {'padding_top', 'padding_bottom', 'background_color',
                              'background_image', 'text_color', 'max_width',
                              'animation'}
            ALLOWED_ANIMATION_VALUES = {
                '', 'fade-in', 'fade-up', 'fade-down',
                'slide-left', 'slide-right', 'zoom-in',
            }
            for k, v in (patch.get('updates') or {}).items():
                if k not in ALLOWED_LAYOUT:
                    continue
                if v in (None, ''):
                    section['layout'].pop(k, None)
                elif k == 'animation':
                    s = str(v)
                    # Reject unknown animation values silently to keep the
                    # CSS class enumeration tight.
                    if s in ALLOWED_ANIMATION_VALUES:
                        if s == '':
                            section['layout'].pop(k, None)
                        else:
                            section['layout'][k] = s
                else:
                    section['layout'][k] = str(v)
            affected.add(sid)

        elif op == 'add_block':
            sid = patch.get('sid')
            section = template['sections'].get(sid)
            if section is None:
                continue
            section.setdefault('blocks', {})
            section.setdefault('block_order', [])
            # BUG FIX (v2.40): per-section block cap so paste-all and bulk
            # block ops can't blow up a section.
            if len(section['block_order']) >= MAX_BLOCKS_PER_SECTION:
                return error_response('VALIDATION_FAILED', 400, {
                    'detail': f'section is at the {MAX_BLOCKS_PER_SECTION}-block limit; remove one before adding more.',
                })
            bid = patch.get('bid') or _sid()
            section['blocks'][bid] = {
                'type': patch.get('block_type') or 'item',
                'settings': patch.get('settings') or {},
            }
            section['block_order'].append(bid)
            affected.add(sid)

        elif op == 'remove_block':
            sid = patch.get('sid')
            bid = patch.get('bid')
            section = template['sections'].get(sid)
            if section is None:
                continue
            section.get('blocks', {}).pop(bid, None)
            section['block_order'] = [x for x in section.get('block_order', []) if x != bid]
            affected.add(sid)

        elif op == 'reorder_blocks':
            sid = patch.get('sid')
            section = template['sections'].get(sid)
            if section is None:
                continue
            new_order = patch.get('block_order') or []
            known = set(section.get('blocks', {}).keys())
            section['block_order'] = [x for x in new_order if x in known]
            affected.add(sid)

        elif op == 'set_block':
            sid = patch.get('sid')
            bid = patch.get('bid')
            key = patch.get('key')
            section = template['sections'].get(sid)
            if section is None or not key:
                continue
            block = section.get('blocks', {}).get(bid)
            if block is None:
                continue
            block.setdefault('settings', {})
            block['settings'][key] = patch.get('value')
            affected.add(sid)

        else:
            return error_response('VALIDATION_FAILED', 400, {'detail': f'unknown op {op!r}'})

    # Phase 2: only record a revision if the template actually changed.
    # Re-loading after patch ops avoids comparing local mutations against
    # the same dict; we compare the original snapshot against `template`.
    if template != pre_snapshot:
        # Build a short summary so the history panel reads well. We
        # describe the FIRST op (most patches are 1-op anyway); for batch
        # patches we mention the count.
        first = patches[0] if patches else {}
        first_op = (first or {}).get('op', 'unknown')
        first_sid = (first or {}).get('sid')
        if len(patches) == 1:
            summary = _summarize_op(first, pre_snapshot, template)
        else:
            summary = f'{len(patches)} edits in batch (first: {first_op})'
        record_revision(
            page_slug=page_slug,
            state=STATE_DRAFT,
            op=first_op,
            snapshot=pre_snapshot,
            op_target_sid=first_sid,
            op_summary=summary,
            created_by=current_user.id if current_user.is_authenticated else None,
        )

    row.set_template(template)
    row.updated_at = datetime.utcnow()
    row.updated_by = current_user.id if current_user.is_authenticated else None
    db.session.commit()

    # Re-render only the sections that changed
    rendered = {}
    for sid in affected:
        if sid in template['sections']:
            rendered[sid] = render_section(sid, template['sections'][sid], reg)

    return jsonify({
        'template':       template,
        'sections_html':  rendered,
        'affected_sids':  sorted(affected),
    }), 200


# ─── Phase 2: Revision history + revert ─────────────────────────────────────

@cms_v2_bp.route('/cms/page/<string:page_slug>/revisions', methods=['GET'])
@requires_role('admin')
def list_revisions(page_slug):
    """Return the most recent revisions for a page, newest first.

    Each row is a snapshot of the template that existed BEFORE the patch
    that's being described — i.e. reverting to revision N restores the
    state from before edit N landed.
    """
    if not _valid_slug(page_slug):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'invalid page slug'})

    state = (request.args.get('state') or STATE_DRAFT).strip()
    if state not in VALID_STATES:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'invalid state'})

    limit = min(int(request.args.get('limit') or 50), 200)

    rows = (PageTemplateRevision.query
            .filter_by(page_slug=page_slug, state=state)
            .order_by(PageTemplateRevision.created_at.desc())
            .limit(limit)
            .all())

    # Hydrate updated_by_name for each row in one pass
    from app.models.user import User
    user_ids = {r.created_by for r in rows if r.created_by}
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    out = []
    for r in rows:
        d = r.to_dict()
        u = users.get(r.created_by)
        d['created_by_name'] = (u.name or u.uid) if u else ('?' if r.created_by else 'system')
        out.append(d)

    return jsonify({'revisions': out, 'count': len(out)}), 200


@cms_v2_bp.route('/cms/page/<string:page_slug>/revert/<int:revision_id>',
                 methods=['POST'])
@requires_role('admin')
def revert_revision(page_slug, revision_id):
    """Restore the page's template to the snapshot stored in revision N.

    Important: reverting itself records a NEW revision (so you can undo a
    revert). The snapshot for the new revision is the BEFORE state of the
    revert — i.e. the current template right now, before we restore.
    """
    if not _valid_slug(page_slug):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'invalid page slug'})

    rev = PageTemplateRevision.query.filter_by(id=revision_id, page_slug=page_slug).first()
    if not rev:
        return error_response('NOT_FOUND', 404, {'detail': 'revision not found'})

    row = _get_or_create_template(page_slug, rev.state)
    pre_snapshot = row.get_template()
    new_template = rev.get_snapshot()

    # Record the revert as its own revision so the user can undo it.
    record_revision(
        page_slug=page_slug,
        state=rev.state,
        op='revert',
        snapshot=pre_snapshot,
        op_summary=f'Reverted to revision #{revision_id}',
        created_by=current_user.id if current_user.is_authenticated else None,
    )

    row.set_template(new_template)
    row.updated_at = datetime.utcnow()
    row.updated_by = current_user.id if current_user.is_authenticated else None
    db.session.commit()

    # Re-render every section in the restored template — the editor will
    # hot-swap the iframe without reloading.
    reg = _registry()
    rendered = {}
    for sid, section in (new_template.get('sections') or {}).items():
        if reg:
            try:
                rendered[sid] = render_section(sid, section, reg)
            except Exception:
                pass

    return jsonify({
        'message':       f'Reverted to revision #{revision_id}.',
        'template':      new_template,
        'sections_html': rendered,
    }), 200


# ─── Diff preview (draft vs published) ──────────────────────────────────────

@cms_v2_bp.route('/cms/page/<string:page_slug>/diff', methods=['GET'])
@requires_role('admin')
def diff_page(page_slug):
    """Compute what would change if the current draft is published.

    Returns:
      {
        added:     [{sid, type, name?}, ...]   # in draft, not in published
        removed:   [{sid, type, name?}, ...]   # in published, not in draft
        modified:  [{sid, type, fields:[{key, before, after}, ...]}, ...]
        reordered: bool — true if `order` arrays differ
        order_before: [...sids in published order]
        order_after:  [...sids in draft order]
        net:       {added, removed, modified}  # counts
        no_published: bool — true if there's no published version yet
      }

    Empty additions/removals/modifications means a no-op publish.
    """
    draft = PageTemplate.query.filter_by(page_slug=page_slug, state=STATE_DRAFT).first()
    if not draft:
        return error_response('NOT_FOUND', 404, {'detail': 'no draft for this page'})
    pub = PageTemplate.query.filter_by(page_slug=page_slug, state=STATE_PUBLISHED).first()

    draft_t = draft.get_template() if draft else {'sections': {}, 'order': []}
    pub_t   = pub.get_template()   if pub   else {'sections': {}, 'order': []}
    d_secs = draft_t.get('sections') or {}
    p_secs = pub_t.get('sections')   or {}
    d_order = draft_t.get('order')   or []
    p_order = pub_t.get('order')     or []

    added, removed, modified = [], [], []
    for sid, sec in d_secs.items():
        if sid not in p_secs:
            added.append({'sid': sid, 'type': sec.get('type'),
                          'name': sec.get('name')})
    for sid, sec in p_secs.items():
        if sid not in d_secs:
            removed.append({'sid': sid, 'type': sec.get('type'),
                            'name': sec.get('name')})
    # Modified: same sid, different shape
    for sid, draft_sec in d_secs.items():
        pub_sec = p_secs.get(sid)
        if pub_sec is None:
            continue  # added, already counted
        field_changes = _diff_section_fields(pub_sec, draft_sec)
        if field_changes:
            modified.append({
                'sid': sid,
                'type': draft_sec.get('type'),
                'name': draft_sec.get('name'),
                'fields': field_changes,
            })

    return jsonify({
        'page_slug':    page_slug,
        'no_published': pub is None,
        'added':        added,
        'removed':      removed,
        'modified':     modified,
        'reordered':    list(d_order) != list(p_order),
        'order_before': p_order,
        'order_after':  d_order,
        'net': {
            'added':    len(added),
            'removed':  len(removed),
            'modified': len(modified),
        },
    }), 200


def _diff_section_fields(pub, draft):
    """Return the list of field-level changes between published and draft
    versions of one section. Only fields that differ are returned."""
    changes = []
    keys_to_check = [
        ('settings',         pub.get('settings') or {},   draft.get('settings') or {}),
        ('layout',           pub.get('layout')   or {},   draft.get('layout')   or {}),
        ('device_visibility', pub.get('device_visibility') or [], draft.get('device_visibility') or []),
    ]
    for group, pa, pb in keys_to_check:
        if isinstance(pa, dict) and isinstance(pb, dict):
            keys = set(pa) | set(pb)
            for k in sorted(keys):
                if pa.get(k) != pb.get(k):
                    changes.append({
                        'key': f'{group}.{k}',
                        'before': pa.get(k),
                        'after':  pb.get(k),
                    })
        elif pa != pb:
            changes.append({'key': group, 'before': pa, 'after': pb})
    # Visibility flag is at top level
    if (pub.get('visible') is False) != (draft.get('visible') is False):
        changes.append({
            'key': 'visible',
            'before': pub.get('visible', True),
            'after':  draft.get('visible', True),
        })
    # Block additions/removals/changes
    pub_blocks   = pub.get('blocks')   or {}
    draft_blocks = draft.get('blocks') or {}
    pub_border   = pub.get('block_order')   or []
    draft_border = draft.get('block_order') or []
    if list(pub_border) != list(draft_border):
        changes.append({
            'key': 'block_order',
            'before': pub_border,
            'after':  draft_border,
        })
    block_keys = set(pub_blocks) | set(draft_blocks)
    for bk in sorted(block_keys):
        if pub_blocks.get(bk) != draft_blocks.get(bk):
            changes.append({
                'key':    f'block[{bk}]',
                'before': pub_blocks.get(bk),
                'after':  draft_blocks.get(bk),
            })
    # Section name change
    if pub.get('name') != draft.get('name'):
        changes.append({
            'key': 'name',
            'before': pub.get('name'),
            'after':  draft.get('name'),
        })
    return changes


# ─── Publish ─────────────────────────────────────────────────────────────────

@cms_v2_bp.route('/cms/page/<string:page_slug>/publish', methods=['POST'])
@requires_role('admin')
def publish_page(page_slug):
    """Copy draft → published. Idempotent — produces the same outcome whether
    a published row exists or not.

    Phase 2: snapshots the existing PUBLISHED template before overwriting,
    so an admin can revert a botched publish.
    """
    draft = PageTemplate.query.filter_by(page_slug=page_slug, state=STATE_DRAFT).first()
    if not draft:
        return error_response('NOT_FOUND', 404, {'detail': 'no draft to publish'})

    pub = PageTemplate.query.filter_by(page_slug=page_slug, state=STATE_PUBLISHED).first()
    now = datetime.utcnow()

    # Snapshot the BEFORE-publish state of the published row so a revert
    # can put the live site back to where it was.
    if pub:
        record_revision(
            page_slug=page_slug,
            state=STATE_PUBLISHED,
            op='publish',
            snapshot=pub.get_template(),
            op_summary='Published draft (overwrote previous published version)',
            created_by=current_user.id if current_user.is_authenticated else None,
        )

    if pub:
        pub.template_json = draft.template_json
        pub.published_at  = now
        pub.published_by  = current_user.id
        pub.updated_at    = now
        pub.updated_by    = current_user.id
    else:
        pub = PageTemplate(
            page_slug=page_slug,
            state=STATE_PUBLISHED,
            template_json=draft.template_json,
            updated_by=current_user.id,
            published_at=now,
            published_by=current_user.id,
        )
        db.session.add(pub)
    db.session.commit()
    return jsonify({'message': 'Published.', 'page_slug': page_slug,
                    'published_at': now.isoformat()}), 200


# ─── Single-section render ───────────────────────────────────────────────────

@cms_v2_bp.route('/cms/render', methods=['GET'])
def render_one_section():
    """Render one section to HTML. Used by the editor to hot-swap sections in
    the iframe without a full reload, and by hydrate.js to live-preview edits.

    Query params: page=<slug>, section=<sid>, state=draft|published, token=...
    """
    page_slug = request.args.get('page')
    sid       = request.args.get('section')
    state     = (request.args.get('state') or STATE_PUBLISHED).strip()
    if not (page_slug and sid):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'page and section required'})
    if state not in VALID_STATES:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'invalid state'})
    if state == STATE_DRAFT:
        token = request.args.get('token')
        if not (_is_admin() or _check_token(page_slug, token)):
            return error_response('UNAUTHORIZED', 401)
    row = PageTemplate.query.filter_by(page_slug=page_slug, state=state).first()
    if not row:
        return error_response('NOT_FOUND', 404)
    template = row.get_template()
    section_data = (template.get('sections') or {}).get(sid)
    if not section_data:
        return error_response('NOT_FOUND', 404, {'detail': f'section {sid!r} not found'})
    reg = _registry()
    if not reg:
        return error_response('SERVER_ERROR', 500, {'detail': 'cms registry not initialized'})
    html = render_section(sid, section_data, reg)
    return jsonify({
        'section_id':   sid,
        'section_type': section_data.get('type'),
        'html':         html,
    }), 200


# ─── SEO ─────────────────────────────────────────────────────────────────────

@cms_v2_bp.route('/cms/page/<string:page_slug>/seo', methods=['GET'])
def get_page_seo(page_slug):
    row = PageSeo.query.filter_by(page_slug=page_slug).first()
    out = dict(DEFAULT_SEO)
    out['page_slug']  = page_slug
    out['updated_at'] = None
    if row:
        out.update({k: v for k, v in row.to_dict().items() if v is not None})
    return jsonify(out), 200


@cms_v2_bp.route('/cms/page/<string:page_slug>/seo', methods=['PATCH'])
@requires_role('admin')
def patch_page_seo(page_slug):
    body = request.get_json(silent=True) or {}
    updates = body.get('updates') or {}
    if not isinstance(updates, dict):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'updates must be an object'})
    # BUG FIX (v2.40): truncate to the column max-lengths instead of risking
    # a 500 on too-long input (SQLite silently accepts but Postgres errors).
    # Better to clip than to fail.
    SEO_MAX = {
        'title':           200, 'description':     400,
        'og_image_url':    500, 'og_title':        200, 'og_description':  400,
        'twitter_card':     40, 'canonical_url':   500, 'robots':           80,
    }
    row = PageSeo.query.filter_by(page_slug=page_slug).first()
    if not row:
        row = PageSeo(page_slug=page_slug)
        db.session.add(row)
    for k, v in updates.items():
        if k not in SEO_FIELDS:
            continue
        if v is None:
            setattr(row, k, None)
            continue
        s = str(v)
        cap = SEO_MAX.get(k)
        if cap and len(s) > cap:
            s = s[:cap]
        setattr(row, k, s)
    row.updated_at = datetime.utcnow()
    row.updated_by = current_user.id
    db.session.commit()
    return jsonify(row.to_dict()), 200


# ─── Backup / restore ────────────────────────────────────────────────────────

@cms_v2_bp.route('/cms/page/<string:page_slug>/export', methods=['GET'])
@requires_role('admin')
def export_page(page_slug):
    """Download the page's draft+published templates as one JSON blob."""
    out = {'page_slug': page_slug, 'exported_at': datetime.utcnow().isoformat() + 'Z'}
    for state in (STATE_DRAFT, STATE_PUBLISHED):
        row = PageTemplate.query.filter_by(page_slug=page_slug, state=state).first()
        out[state] = row.get_template() if row else None
    return jsonify(out), 200


@cms_v2_bp.route('/cms/page/<string:page_slug>/import', methods=['POST'])
@requires_role('admin')
def import_page(page_slug):
    """Replace this page's draft template with the one in the body.
    Body: { template: {sections, order} } OR a previously-exported blob
    (in which case the `draft` key is used).

    BUG FIX (v2.40): the previous implementation accepted any dict — admins
    could (accidentally or otherwise) import a 1000-section template and
    bypass the 25-section soft cap, plant unknown section types, etc. Now
    validates structure + drops unknown types + enforces the same caps as
    the patch ops.
    """
    body = request.get_json(silent=True) or {}
    template = body.get('template') or body.get('draft')
    if not isinstance(template, dict):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'template must be an object'})

    reg = _registry()
    sections_in = template.get('sections') or {}
    order_in    = template.get('order')    or []
    if not isinstance(sections_in, dict):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'sections must be an object'})
    if not isinstance(order_in, list):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'order must be a list'})

    # Build a clean template: drop unknown section types, cap order length,
    # cap blocks per section, drop block_order entries that don't exist in blocks.
    clean_sections = {}
    clean_order = []
    for sid in order_in[:MAX_SECTIONS_PER_PAGE]:
        if not isinstance(sid, str) or sid not in sections_in:
            continue
        sec = sections_in[sid]
        if not isinstance(sec, dict):
            continue
        type_id = sec.get('type')
        if not (reg and reg.get(type_id)):
            # Skip sections with unknown types — never silently store them
            continue
        blocks_in = sec.get('blocks') if isinstance(sec.get('blocks'), dict) else {}
        block_order_in = sec.get('block_order') if isinstance(sec.get('block_order'), list) else []
        # Cap block count + drop dangling order entries
        valid_block_ids = [bid for bid in block_order_in if isinstance(bid, str) and bid in blocks_in]
        valid_block_ids = valid_block_ids[:MAX_BLOCKS_PER_SECTION]
        clean_blocks = {bid: blocks_in[bid] for bid in valid_block_ids}
        clean_sec = {
            'type':        type_id,
            'settings':    sec.get('settings') or {},
            'visible':     bool(sec.get('visible', True)),
            'blocks':      clean_blocks,
            'block_order': valid_block_ids,
        }
        # Carry over optional fields if present
        for k in ('layout', 'device_visibility', 'name'):
            if k in sec:
                clean_sec[k] = sec[k]
        clean_sections[sid] = clean_sec
        clean_order.append(sid)

    template = {'sections': clean_sections, 'order': clean_order}
    row = _get_or_create_template(page_slug, STATE_DRAFT)
    row.set_template(template)
    row.updated_at = datetime.utcnow()
    row.updated_by = current_user.id
    db.session.commit()
    sections_html = render_page(template, reg) if reg else {}
    return jsonify({
        'page_slug':     page_slug,
        'template':      template,
        'sections_html': sections_html,
        'message':       'Imported.',
        # Tell the FE if anything got dropped during validation
        'dropped_count': len(order_in) - len(clean_order),
    }), 200


@cms_v2_bp.route('/cms/page/<string:page_slug>/create', methods=['POST'])
@requires_role('admin')
def create_blank_page(page_slug):
    """Create an empty draft for a brand-new page slug. Refuses if a draft
    already exists at that slug — admins can use /duplicate or /import to
    populate an existing slug."""
    if not _valid_slug(page_slug):
        return error_response('VALIDATION_FAILED', 400,
            {'detail': 'invalid page_slug — use lowercase letters, digits, and hyphens (max 80 chars)'})
    if PageTemplate.query.filter_by(page_slug=page_slug, state=STATE_DRAFT).first():
        return error_response('VALIDATION_FAILED', 400,
                              {'detail': 'a draft already exists for this slug'})
    row = PageTemplate(
        page_slug=page_slug, state=STATE_DRAFT,
        template_json='{"sections":{},"order":[]}',
        updated_by=current_user.id,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({'page_slug': page_slug, 'message': 'Page created.'}), 201


@cms_v2_bp.route('/cms/page/<string:source_slug>/duplicate', methods=['POST'])
@requires_role('admin')
def duplicate_page(source_slug):
    """Copy source page's draft template to a new page slug.
    Body: { target_slug: '...' }"""
    body = request.get_json(silent=True) or {}
    target = (body.get('target_slug') or '').strip()
    if not _valid_slug(target):
        return error_response('VALIDATION_FAILED', 400,
            {'detail': 'invalid target_slug — use lowercase letters, digits, and hyphens (max 80 chars)'})
    src = PageTemplate.query.filter_by(page_slug=source_slug, state=STATE_DRAFT).first()
    if not src:
        return error_response('NOT_FOUND', 404, {'detail': 'no draft on source page'})
    if PageTemplate.query.filter_by(page_slug=target, state=STATE_DRAFT).first():
        return error_response('VALIDATION_FAILED', 400, {'detail': 'target page already has a draft'})
    new_row = PageTemplate(
        page_slug=target, state=STATE_DRAFT,
        template_json=src.template_json,
        updated_by=current_user.id,
    )
    db.session.add(new_row)
    db.session.commit()
    return jsonify({'page_slug': target, 'message': 'Duplicated.'}), 201


# ─── Preview tokens ──────────────────────────────────────────────────────────

@cms_v2_bp.route('/cms/page/<string:page_slug>/preview-token', methods=['POST'])
@requires_role('admin')
def issue_preview_token(page_slug):
    """Issue a 7-day token that grants read-only access to the page draft."""
    body = request.get_json(silent=True) or {}
    # BUG FIX (v2.40): int() raised on non-numeric input → 500 instead of 400
    try:
        ttl_days = int(body.get('ttl_days') or 7)
    except (TypeError, ValueError):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'ttl_days must be an integer'})
    if ttl_days < 1 or ttl_days > 60:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'ttl_days 1..60'})
    tok = PreviewToken.issue(page_slug, created_by=current_user.id, ttl_days=ttl_days)
    db.session.add(tok)
    db.session.commit()
    return jsonify({'token': tok.token, 'expires_at': tok.expires_at.isoformat(),
                    'page_slug': page_slug}), 201
