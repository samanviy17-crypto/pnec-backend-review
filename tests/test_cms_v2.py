# tests/test_cms_v2.py
# Coverage for the v2 CMS API: sections registry, page read, draft patch ops,
# render API, publish, preview tokens.

import json
from datetime import datetime, timedelta

import pytest

from app import db
from app.models.page_template import PageTemplate, STATE_DRAFT, STATE_PUBLISHED
from app.models.preview_token import PreviewToken
from app.models.user import User


# ── Sections registry ────────────────────────────────────────────────────────

def test_registry_lists_starter_sections(client):
    res = client.get('/api/cms/sections-registry')
    assert res.status_code == 200
    body = res.get_json()
    types = {s['type'] for s in body['sections']}
    assert {'hero', 'text_block', 'image_with_text', 'faq'}.issubset(types)
    # Each schema has the minimum fields
    for s in body['sections']:
        assert 'type' in s
        assert 'label' in s
        assert isinstance(s.get('settings'), list)


def test_faq_section_supports_blocks_end_to_end(client, app):
    _login_admin(client, app)
    # Add FAQ section
    res = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'faq'}]
    }).get_json()
    sid = res['template']['order'][0]
    # Add three Q&A blocks
    res = client.patch('/api/cms/page/home/draft', json={
        'patches': [
            {'op': 'add_block', 'sid': sid, 'block_type': 'qa',
             'settings': {'question': 'Q1?', 'answer': 'A1'}},
            {'op': 'add_block', 'sid': sid, 'block_type': 'qa',
             'settings': {'question': 'Q2?', 'answer': 'A2'}},
            {'op': 'add_block', 'sid': sid, 'block_type': 'qa',
             'settings': {'question': 'Q3?', 'answer': 'A3'}},
        ]
    }).get_json()
    section = res['template']['sections'][sid]
    assert len(section['block_order']) == 3
    # Rendered HTML should contain all three questions
    html = res['sections_html'][sid]
    assert 'Q1?' in html and 'Q2?' in html and 'Q3?' in html


def test_faq_block_reorder(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'faq'}]
    }).get_json()
    sid = a['template']['order'][0]
    add_blocks = client.patch('/api/cms/page/home/draft', json={
        'patches': [
            {'op': 'add_block', 'sid': sid, 'block_type': 'qa', 'settings': {'question': 'A'}},
            {'op': 'add_block', 'sid': sid, 'block_type': 'qa', 'settings': {'question': 'B'}},
        ]
    }).get_json()
    block_order = add_blocks['template']['sections'][sid]['block_order']
    assert len(block_order) == 2
    # Reverse the order
    reversed_order = list(reversed(block_order))
    res = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'reorder_blocks', 'sid': sid, 'block_order': reversed_order}]
    }).get_json()
    assert res['template']['sections'][sid]['block_order'] == reversed_order


def test_registry_drift_guard_each_section_has_settings_list(client):
    res = client.get('/api/cms/sections-registry')
    body = res.get_json()
    for s in body['sections']:
        for field in s['settings']:
            assert 'id' in field, f"{s['type']} field missing id"
            assert 'type' in field, f"{s['type']} field missing type"


# ── Page read (empty state is OK) ────────────────────────────────────────────

def test_get_page_returns_empty_when_no_template(client):
    res = client.get('/api/cms/page/home')
    assert res.status_code == 200
    body = res.get_json()
    assert body['page_slug'] == 'home'
    assert body['state'] == 'published'
    assert body['template'] == {'sections': {}, 'order': []}
    assert body['sections_html'] == {}


def test_get_page_invalid_state_400(client):
    res = client.get('/api/cms/page/home?state=bogus')
    assert res.status_code == 400


def test_get_page_draft_unauthorized_without_admin_or_token(client):
    res = client.get('/api/cms/page/home?state=draft')
    assert res.status_code == 401


# ── Helpers for admin client ─────────────────────────────────────────────────

def _login_admin(client, app):
    """Sign in as the seeded admin via flask-login session_transaction."""
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
        assert admin is not None, "conftest should seed an admin"
        admin_id = admin.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True
    return admin_id


# ── Patches: add / set / reorder / remove ────────────────────────────────────

def test_admin_can_add_a_hero_section(client, app):
    _login_admin(client, app)
    res = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    })
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert len(body['template']['order']) == 1
    sid = body['template']['order'][0]
    assert body['template']['sections'][sid]['type'] == 'hero'
    # Default settings filled in from schema
    assert body['template']['sections'][sid]['settings']['headline'] == 'Neighbors Helping Neighbors'
    # Affected sids include the new section
    assert sid in body['affected_sids']
    # Rendered HTML returned for the affected section, and it contains the headline
    assert 'cms-section-' + sid in body['sections_html'][sid]
    assert 'Neighbors Helping Neighbors' in body['sections_html'][sid]


def test_admin_can_update_a_setting_via_set_op(client, app):
    _login_admin(client, app)
    add = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = add['template']['order'][0]
    res = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'set', 'sid': sid, 'key': 'headline', 'value': 'Custom headline'}]
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body['template']['sections'][sid]['settings']['headline'] == 'Custom headline'
    assert 'Custom headline' in body['sections_html'][sid]


def test_admin_can_reorder_sections(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}, {'op': 'add', 'type': 'text_block'}]
    }).get_json()
    sid_a, sid_b = a['template']['order']
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'reorder', 'order': [sid_b, sid_a]}]
    })
    assert r.status_code == 200
    assert r.get_json()['template']['order'] == [sid_b, sid_a]


def test_admin_can_remove_a_section(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}, {'op': 'add', 'type': 'text_block'}]
    }).get_json()
    sid_a, sid_b = a['template']['order']
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'remove', 'sid': sid_a}]
    })
    assert r.status_code == 200
    body = r.get_json()
    assert sid_a not in body['template']['sections']
    assert body['template']['order'] == [sid_b]


def test_admin_can_duplicate_a_section(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero',
                     'settings': {'headline': 'Original', 'sub_headline': 'sub',
                                  'cta_label': 'go', 'cta_url': '#',
                                  'text_alignment': 'center'}}]
    }).get_json()
    sid = a['template']['order'][0]
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'duplicate', 'sid': sid}]
    })
    assert r.status_code == 200
    body = r.get_json()
    assert len(body['template']['order']) == 2
    new_sid = body['template']['order'][1]
    assert new_sid != sid
    # Same settings
    assert (body['template']['sections'][new_sid]['settings']['headline']
            == body['template']['sections'][sid]['settings']['headline']
            == 'Original')


def test_admin_can_toggle_visibility(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = a['template']['order'][0]
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'visibility', 'sid': sid, 'visible': False}]
    })
    assert r.status_code == 200
    assert r.get_json()['template']['sections'][sid]['visible'] is False


def test_unknown_op_400(client, app):
    _login_admin(client, app)
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'sabotage'}]
    })
    assert r.status_code == 400


def test_add_with_unknown_type_400(client, app):
    _login_admin(client, app)
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'made_up_type'}]
    })
    assert r.status_code == 400


# ── Publish ──────────────────────────────────────────────────────────────────

def test_publish_copies_draft_to_published(client, app):
    _login_admin(client, app)
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    })
    res = client.post('/api/cms/page/home/publish')
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body['page_slug'] == 'home'
    # Now the published-state read should return the same template
    pub = client.get('/api/cms/page/home').get_json()
    assert pub['state'] == 'published'
    assert len(pub['template']['order']) == 1


def test_publish_is_idempotent(client, app):
    _login_admin(client, app)
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    })
    r1 = client.post('/api/cms/page/home/publish')
    r2 = client.post('/api/cms/page/home/publish')
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_publish_404_when_no_draft(client, app):
    _login_admin(client, app)
    r = client.post('/api/cms/page/no-such-page/publish')
    assert r.status_code == 404


# ── Render API ───────────────────────────────────────────────────────────────

def test_render_one_section(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = a['template']['order'][0]
    # Admin can render draft
    r = client.get(f'/api/cms/render?page=home&section={sid}&state=draft')
    assert r.status_code == 200
    body = r.get_json()
    assert body['section_id'] == sid
    assert body['section_type'] == 'hero'
    assert f'cms-section-{sid}' in body['html']


def test_render_404_for_missing_section(client, app):
    _login_admin(client, app)
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    })
    r = client.get('/api/cms/render?page=home&section=does-not-exist&state=draft')
    assert r.status_code == 404


def test_render_validation_400_when_params_missing(client):
    r = client.get('/api/cms/render')
    assert r.status_code == 400


# ── Preview tokens ───────────────────────────────────────────────────────────

def test_admin_can_issue_preview_token(client, app):
    _login_admin(client, app)
    r = client.post('/api/cms/page/home/preview-token', json={'ttl_days': 7})
    assert r.status_code == 201
    body = r.get_json()
    assert 'token' in body and len(body['token']) > 20
    assert body['page_slug'] == 'home'


def test_preview_token_grants_draft_read(client, app):
    """A valid preview token lets an unauthenticated client read the draft."""
    _login_admin(client, app)
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    })
    tok = client.post('/api/cms/page/home/preview-token').get_json()['token']
    # Use a fresh client (no inherited session cookies / auth state)
    fresh = app.test_client()
    r = fresh.get(f'/api/cms/page/home?state=draft&token={tok}')
    assert r.status_code == 200
    assert len(r.get_json()['template']['order']) == 1


def test_anonymous_without_token_cannot_read_draft(client, app):
    """No admin auth, no token → 401 on draft reads."""
    fresh = app.test_client()
    r = fresh.get('/api/cms/page/home?state=draft')
    assert r.status_code == 401


def test_expired_preview_token_rejected(client, app):
    _login_admin(client, app)
    # Manually insert an expired token
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
        tok = PreviewToken.issue('home', created_by=admin.id, ttl_days=1)
        tok.expires_at = datetime.utcnow() - timedelta(days=1)
        db.session.add(tok)
        db.session.commit()
        token_str = tok.token
    with client.session_transaction() as sess:
        sess.clear()
    r = client.get(f'/api/cms/page/home?state=draft&token={token_str}')
    assert r.status_code == 401


# ── Auth on writes ───────────────────────────────────────────────────────────

def test_anonymous_cannot_patch_draft(client):
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    })
    assert r.status_code in (401, 403)


def test_anonymous_cannot_publish(client):
    r = client.post('/api/cms/page/home/publish')
    assert r.status_code in (401, 403)


# ── v2.19: rename op + cross-page search ─────────────────────────────────────

def test_admin_can_rename_a_section(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = a['template']['order'][0]
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'rename', 'sid': sid, 'name': 'Above-the-fold hero'}]
    })
    assert r.status_code == 200
    assert r.get_json()['template']['sections'][sid]['name'] == 'Above-the-fold hero'


def test_renaming_with_blank_string_clears_the_name(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = a['template']['order'][0]
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'rename', 'sid': sid, 'name': 'Custom name'}]
    })
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'rename', 'sid': sid, 'name': ''}]
    })
    assert r.status_code == 200
    # blank → key is removed (not present, or None)
    sec = r.get_json()['template']['sections'][sid]
    assert sec.get('name') in (None, '')


def test_rename_unknown_sid_is_ignored(client, app):
    _login_admin(client, app)
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'rename', 'sid': 'sec_doesnt_exist', 'name': 'x'}]
    })
    # Treat as no-op (no crash, no 500)
    assert r.status_code == 200


def test_search_finds_section_by_text(client, app):
    _login_admin(client, app)
    add = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = add['template']['order'][0]
    # Update the hero's headline with a unique searchable string
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'set', 'sid': sid, 'key': 'headline',
                     'value': 'Earthquake preparedness rocks UNIQUEZZ'}]
    })
    r = client.get('/api/cms/search?q=uniquezz')
    assert r.status_code == 200
    body = r.get_json()
    assert body['count'] >= 1
    assert any(h['sid'] == sid for h in body['hits'])


def test_search_filters_by_type(client, app):
    _login_admin(client, app)
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    })
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'text_block'}]
    })
    r = client.get('/api/cms/search?type=text_block')
    assert r.status_code == 200
    hits = r.get_json()['hits']
    assert all(h['type'] == 'text_block' for h in hits)


def test_search_finds_renamed_section_by_name(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = a['template']['order'][0]
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'rename', 'sid': sid, 'name': 'Volunteer banner XYZQ'}]
    })
    r = client.get('/api/cms/search?q=xyzq')
    assert r.status_code == 200
    hits = r.get_json()['hits']
    assert any(h['sid'] == sid and h['name'] == 'Volunteer banner XYZQ' for h in hits)


def test_search_anonymous_blocked(client):
    r = client.get('/api/cms/search?q=anything')
    assert r.status_code in (401, 403)


# ── v2.26: publish diff ──────────────────────────────────────────────────────

def test_diff_when_no_published_yet(client, app):
    _login_admin(client, app)
    # Add a section, then ask for diff before publishing for the first time
    add = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = add['template']['order'][0]
    r = client.get('/api/cms/page/home/diff')
    assert r.status_code == 200
    body = r.get_json()
    assert body['no_published'] is True
    assert any(a['sid'] == sid for a in body['added'])
    assert body['removed'] == []
    assert body['modified'] == []


def test_diff_after_publish_is_empty(client, app):
    _login_admin(client, app)
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    })
    client.post('/api/cms/page/home/publish')
    r = client.get('/api/cms/page/home/diff')
    assert r.status_code == 200
    body = r.get_json()
    assert body['no_published'] is False
    assert body['added'] == []
    assert body['removed'] == []
    assert body['modified'] == []
    assert body['reordered'] is False
    assert body['net'] == {'added': 0, 'removed': 0, 'modified': 0}


def test_diff_detects_added_removed_modified(client, app):
    _login_admin(client, app)
    # Build a baseline + publish it
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = a['template']['order'][0]
    b = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'text_block'}]
    }).get_json()
    text_sid = [s for s in b['template']['order'] if s != sid][0]
    client.post('/api/cms/page/home/publish')
    # Now make some changes that haven't been published yet:
    #   1. modify hero headline
    #   2. delete the text block
    #   3. add a new FAQ
    client.patch('/api/cms/page/home/draft', json={
        'patches': [
            {'op': 'set',    'sid': sid,      'key': 'headline', 'value': 'Brand new headline'},
            {'op': 'remove', 'sid': text_sid},
            {'op': 'add',    'type': 'faq'},
        ]
    })
    r = client.get('/api/cms/page/home/diff')
    assert r.status_code == 200
    body = r.get_json()
    assert any(rmv['sid'] == text_sid for rmv in body['removed']),  body
    assert any(m['sid'] == sid       for m in body['modified']),    body
    assert body['net']['added']    >= 1
    assert body['net']['modified'] >= 1
    assert body['net']['removed'] == 1


def test_diff_anonymous_blocked(client):
    r = client.get('/api/cms/page/home/diff')
    assert r.status_code in (401, 403)


def test_import_caps_at_25_sections(client, app):
    """Import endpoint must enforce the same 25-section cap as the add op."""
    _login_admin(client, app)
    # Build a 30-section import — extras should be silently dropped, not stored
    template = {'sections': {}, 'order': []}
    for i in range(30):
        sid = f's{i:03d}'
        template['sections'][sid] = {'type': 'text_block', 'settings': {'heading': f'H{i}'}}
        template['order'].append(sid)
    r = client.post('/api/cms/page/imp-test/import', json={'template': template})
    assert r.status_code == 200
    body = r.get_json()
    assert len(body['template']['order']) == 25
    assert body['dropped_count'] == 5


def test_import_drops_unknown_section_types(client, app):
    _login_admin(client, app)
    template = {
        'sections': {
            's1': {'type': 'hero',         'settings': {}},
            's2': {'type': 'made_up_type', 'settings': {}},  # should be dropped
            's3': {'type': 'text_block',   'settings': {}},
        },
        'order': ['s1', 's2', 's3'],
    }
    r = client.post('/api/cms/page/imp-types/import', json={'template': template})
    assert r.status_code == 200
    body = r.get_json()
    types = [body['template']['sections'][sid]['type'] for sid in body['template']['order']]
    assert types == ['hero', 'text_block']
    assert body['dropped_count'] == 1


def test_add_block_enforces_50_block_limit(client, app):
    """Per-section block cap (v2.40) — bulk paste shouldn't blow up a section
    with thousands of blocks."""
    _login_admin(client, app)
    add = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'faq'}]
    }).get_json()
    sid = add['template']['order'][0]
    # Fill to the limit
    for _ in range(50):
        r = client.patch('/api/cms/page/home/draft', json={
            'patches': [{'op': 'add_block', 'sid': sid, 'block_type': 'item',
                         'settings': {'question': 'q', 'answer': 'a'}}]
        })
        assert r.status_code == 200, r.get_data(as_text=True)
    # 51st should be rejected
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add_block', 'sid': sid, 'block_type': 'item'}]
    })
    assert r.status_code == 400


def test_layout_op_persists_animation_value(client, app):
    """Per-section entrance animation (v2.25) was silently dropped because
    'animation' wasn't in the layout-op allowlist. Regression test for v2.40."""
    _login_admin(client, app)
    add = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = add['template']['order'][0]
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'layout', 'sid': sid, 'updates': {'animation': 'fade-up'}}]
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    sec = r.get_json()['template']['sections'][sid]
    assert sec.get('layout', {}).get('animation') == 'fade-up'


def test_layout_op_rejects_unknown_animation_value(client, app):
    _login_admin(client, app)
    add = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = add['template']['order'][0]
    # Garbage value should be silently dropped (not stored)
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'layout', 'sid': sid,
                     'updates': {'animation': '<script>alert(1)</script>'}}]
    })
    assert r.status_code == 200
    sec = r.get_json()['template']['sections'][sid]
    assert 'animation' not in (sec.get('layout') or {})


def test_layout_op_clears_animation_on_empty_string(client, app):
    _login_admin(client, app)
    add = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = add['template']['order'][0]
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'layout', 'sid': sid, 'updates': {'animation': 'fade-up'}}]
    })
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'layout', 'sid': sid, 'updates': {'animation': ''}}]
    })
    assert r.status_code == 200
    sec = r.get_json()['template']['sections'][sid]
    assert 'animation' not in (sec.get('layout') or {})


def test_duplicate_enforces_25_section_limit(client, app):
    """Bulk-duplicate (v2.20) must respect the same 25-section soft limit
    that `add` does — otherwise an admin could blast past it.
    Regression for bug found in v2.37.
    """
    _login_admin(client, app)
    # Fill the page right up to the limit (25 sections)
    for _ in range(25):
        client.patch('/api/cms/page/home/draft', json={
            'patches': [{'op': 'add', 'type': 'text_block'}]
        })
    body = client.get('/api/cms/page/home?state=draft').get_json()
    sid = body['template']['order'][0]
    # Now duplicating should be rejected
    r = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'duplicate', 'sid': sid}]
    })
    assert r.status_code == 400, r.get_data(as_text=True)
    err = r.get_json() or {}
    detail = (err.get('detail') or err.get('error', {}).get('detail') or '').lower()
    assert '25' in detail or 'limit' in detail


def test_draft_convenience_endpoint_returns_draft_not_published(client, app):
    """GET /api/cms/page/<slug>/draft should return draft, not published.

    Regression test for v2.36 bug: the convenience endpoint was forgetting
    to set state=draft, so it returned the published template silently.
    """
    _login_admin(client, app)
    # Add a hero, then publish — now draft and published are equal
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    })
    client.post('/api/cms/page/home/publish')
    # Modify the draft only
    sid = client.get('/api/cms/page/home?state=draft').get_json()['template']['order'][0]
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'set', 'sid': sid, 'key': 'headline', 'value': 'DRAFT-ONLY-VALUE'}]
    })
    # The convenience endpoint should return the draft (with the new value)
    r = client.get('/api/cms/page/home/draft')
    assert r.status_code == 200
    body = r.get_json()
    assert body['state'] == 'draft', body
    assert body['template']['sections'][sid]['settings']['headline'] == 'DRAFT-ONLY-VALUE'


def test_diff_detects_reorder(client, app):
    _login_admin(client, app)
    a = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    b = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'text_block'}]
    }).get_json()
    client.post('/api/cms/page/home/publish')
    # Reverse the order in the draft
    reversed_order = list(reversed(b['template']['order']))
    client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'reorder', 'order': reversed_order}]
    })
    r = client.get('/api/cms/page/home/diff')
    body = r.get_json()
    assert body['reordered'] is True
    assert body['order_before'] != body['order_after']
