# tests/test_cms_stega.py
# Round-trip and renderer-integration tests for the stega filter.

from app.services.cms_stega import encode, decode, SENTINEL


def test_encode_decode_round_trip():
    payload = {'sid': 'abc123', 'field': 'headline'}
    text = 'Hello world'
    out = encode(payload, text)
    assert out.endswith(text)
    assert out.startswith(SENTINEL)
    decoded, remaining = decode(out)
    assert decoded == payload
    assert remaining == text


def test_decode_returns_none_for_plain_text():
    decoded, remaining = decode('No stega here')
    assert decoded is None
    assert remaining == 'No stega here'


def test_encode_handles_unicode_in_text():
    payload = {'sid': 'x', 'field': 'y'}
    text = 'Néighbors — Helping each other'
    out = encode(payload, text)
    decoded, remaining = decode(out)
    assert decoded == payload
    assert remaining == text


def test_render_emits_stega_in_hero(client, app):
    """The hero section template uses cms_stega for headline/sub_headline/cta_label.
    Rendering should embed the payload before each visible field."""
    from app.models.user import User
    with app.app_context():
        admin_id = User.query.filter_by(role='admin').first().id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True
    res = client.patch('/api/cms/page/home/draft', json={
        'patches': [{'op': 'add', 'type': 'hero',
                     'settings': {'headline': 'Hello',
                                  'sub_headline': 'World',
                                  'cta_label': 'Go',
                                  'cta_url': '#',
                                  'image_url': '',
                                  'text_alignment': 'center'}}]
    }).get_json()
    sid = res['template']['order'][0]
    html = res['sections_html'][sid]
    # The rendered HTML should contain the sentinel zero-width sequence
    # right before the headline.
    assert SENTINEL in html
    # And the visible text should still appear once zero-width chars are stripped.
    plain = html.replace('​', '').replace('‌', '')
    assert '>Hello<' in plain
