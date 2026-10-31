# tests/test_cms_theme.py
# Coverage for the theme tokens API.

import pytest
from app.models.user import User


def _login_admin(client, app):
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
        admin_id = admin.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True
    return admin_id


def test_schema_lists_grouped_tokens(client):
    res = client.get('/api/cms/theme/schema')
    assert res.status_code == 200
    body = res.get_json()
    assert 'groups' in body
    assert 'colors' in body['groups']
    assert any(t['key'] == 'color_primary' for t in body['groups']['colors'])


def test_get_theme_returns_defaults_when_empty(client):
    res = client.get('/api/cms/theme')
    assert res.status_code == 200
    body = res.get_json()
    assert body['tokens']['color_primary'] == '#1e3a8a'


def test_admin_can_patch_draft_tokens(client, app):
    _login_admin(client, app)
    res = client.patch('/api/cms/theme/draft', json={'updates': {'color_primary': '#ff0000'}})
    assert res.status_code == 200
    assert res.get_json()['tokens']['color_primary'] == '#ff0000'


def test_unknown_token_keys_are_rejected(client, app):
    _login_admin(client, app)
    res = client.patch('/api/cms/theme/draft', json={'updates': {'evil_key': 'oh no'}})
    assert res.status_code == 200
    assert 'evil_key' not in res.get_json()['tokens']


def test_publish_copies_draft_to_published(client, app):
    _login_admin(client, app)
    client.patch('/api/cms/theme/draft', json={'updates': {'color_primary': '#abc123'}})
    res = client.post('/api/cms/theme/publish')
    assert res.status_code == 200
    pub = client.get('/api/cms/theme').get_json()
    assert pub['tokens']['color_primary'] == '#abc123'


def test_anonymous_cannot_patch(client):
    res = client.patch('/api/cms/theme/draft', json={'updates': {'color_primary': '#000'}})
    assert res.status_code in (401, 403)


def test_theme_css_endpoint(client, app):
    _login_admin(client, app)
    client.patch('/api/cms/theme/draft', json={'updates': {'color_primary': '#abcdef'}})
    client.post('/api/cms/theme/publish')
    res = client.get('/api/cms/theme.css')
    assert res.status_code == 200
    assert res.mimetype == 'text/css'
    assert b'--cms-color-primary: #abcdef' in res.data


def test_theme_css_strips_injection_attempts(client, app):
    """Regression for v2.40 — admin can't break out of CSS property syntax."""
    _login_admin(client, app)
    # Plant an injection-shaped value
    client.patch('/api/cms/theme/draft', json={
        'updates': {'color_primary': 'red; color: blue; --evil: 1'}
    })
    client.post('/api/cms/theme/publish')
    res = client.get('/api/cms/theme.css')
    assert res.status_code == 200
    css = res.data.decode()
    # Semicolons inside the value are gone (only the property terminator remains)
    assert '--cms-color-primary: red color: blue --evil: 1;' in css
    # No injected --evil custom property leaked out
    assert '--evil:' not in css.replace('--cms-color-primary: red color: blue --evil: 1;', '')


def test_theme_css_drops_expression_hooks(client, app):
    _login_admin(client, app)
    client.patch('/api/cms/theme/draft', json={
        'updates': {'color_primary': 'expression(alert(1))', 'color_accent': '#ff0000'}
    })
    client.post('/api/cms/theme/publish')
    res = client.get('/api/cms/theme.css')
    css = res.data.decode()
    # The expression token was dropped entirely (note: --cms-color-primary-text
    # is a separate key and remains, so we check for the property declaration)
    assert '--cms-color-primary:' not in css
    assert 'expression' not in css
    # Other tokens still come through
    assert '--cms-color-accent: #ff0000' in css


def test_visibility_op_persists_device_list(client, app):
    """device_visibility patch op stores the list and renderer applies CSS classes."""
    _login_admin(client, app)
    add = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero'}]
    }).get_json()
    sid = add['template']['order'][0]
    res = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'device_visibility', 'sid': sid, 'devices': ['desktop']}]
    }).get_json()
    section = res['template']['sections'][sid]
    assert section['device_visibility'] == ['desktop']
    # Rendered HTML should include CSS classes that hide it on tablet+mobile
    html = res['sections_html'][sid]
    assert 'cms-hide-tablet' in html
    assert 'cms-hide-mobile' in html
    assert 'cms-hide-desktop' not in html
