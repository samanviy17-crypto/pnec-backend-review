"""Production review policy: exact Pages origin, cross-site cookies, no broad CORS."""
import secrets

from app import create_app, db


def test_pages_review_origin_policy(monkeypatch, tmp_path):
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', secrets.token_urlsafe(48))
    monkeypatch.setenv('FRONTEND_URL', 'https://samanviy17-crypto.github.io/pnec-frontend-review')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'review.db'))
    monkeypatch.setenv('SECURITY_STATE_PATH', str(tmp_path / 'limits.json'))
    for name in ('DB_ENDPOINT', 'DB_USERNAME', 'DB_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    app = create_app()
    assert app.config['SESSION_COOKIE_SECURE']
    assert app.config['SESSION_COOKIE_SAMESITE'] == 'None'
    assert app.config['FRONTEND_URL'].endswith('/pnec-frontend-review')
    client = app.test_client()
    origin = 'https://samanviy17-crypto.github.io'
    allowed = client.options('/api/auth/profile', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'PATCH',
        'Access-Control-Request-Headers': 'Authorization,Content-Type,X-CSRF-Token'})
    assert allowed.headers['Access-Control-Allow-Origin'] == origin
    assert allowed.headers['Access-Control-Allow-Credentials'] == 'true'
    for rejected in ('https://powaynec.com', 'https://whitelunarium.github.io',
                     origin + '.attacker.example', 'http://localhost:4000'):
        response = client.get('/api/health', headers={'Origin': rejected})
        assert 'Access-Control-Allow-Origin' not in response.headers
        assert client.post('/api/auth/logout', headers={'Origin': rejected}).status_code == 403
    assert client.get('/api/health').json['status'] == 'ok'
    with app.app_context():
        db.engine.dispose()
