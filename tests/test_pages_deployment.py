"""Project-site CORS and route contracts, using the isolated existing app fixture."""
import pytest

# Preserve the existing production origin policy; portfolio expansion is pending.
ORIGIN = 'https://pnec-review.invalid'


@pytest.mark.parametrize('path,status', [
    ('/api/health', 200),
    ('/api/preparedness/quiz', 200),
    ('/api/preparedness', 401),
    ('/api/check-ins', 401),
    ('/api/auth/me', 401),
])
def test_pages_route_contract(client, path, status):
    response = client.get(path, headers={'Origin': ORIGIN})
    assert response.status_code == status
    assert response.headers['Access-Control-Allow-Origin'] == ORIGIN
    assert response.headers['Access-Control-Allow-Credentials'] == 'true'
    if path == '/api/preparedness/quiz':
        assert len(response.json['questions']) == 10


def test_pages_profile_preflight(client):
    response = client.options('/api/auth/profile', headers={
        'Origin': ORIGIN,
        'Access-Control-Request-Method': 'PATCH',
        'Access-Control-Request-Headers': 'authorization,content-type',
    })
    assert response.status_code == 200
    assert response.headers['Access-Control-Allow-Origin'] == ORIGIN
    assert 'PATCH' in response.headers['Access-Control-Allow-Methods']
    assert 'authorization' in response.headers['Access-Control-Allow-Headers'].lower()


@pytest.mark.parametrize('origin', [
    'https://samanviy17-crypto.github.io.attacker.example',
    'http://samanviy17-crypto.github.io',
    'https://untrusted.example',
    'https://samanviy17-crypto.github.io',
])
def test_unapproved_origins_not_allowed(client, origin):
    response = client.get('/api/health', headers={'Origin': origin})
    assert response.status_code == 200
    assert 'Access-Control-Allow-Origin' not in response.headers


@pytest.mark.parametrize('origin', [
    'http://127.0.0.1:4500',
    'https://pnec-review.invalid',
    'https://whitelunarium.github.io',
])
def test_existing_origins_preserved(client, origin):
    response = client.get('/api/health', headers={'Origin': origin})
    assert response.headers['Access-Control-Allow-Origin'] == origin
