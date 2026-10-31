"""Production security contract; synthetic credentials and disposable state only."""
import io
import json
import multiprocessing
import os
import secrets
import time

import pytest
from flask import Flask

from app import db
from app.config import Config, configure_production, get_config
from app.models.user import User
from app.utils import shared_limits


@pytest.fixture
def production_environment(monkeypatch):
    for name in ('SECRET_KEY', 'DATABASE_URL', 'DB_ENDPOINT', 'DB_USERNAME', 'DB_PASSWORD', 'FRONTEND_URL', 'BEARER_TOKEN_MAX_AGE', 'SECURITY_STATE_PATH'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('SECRET_KEY', secrets.token_hex(32))
    monkeypatch.setenv('FRONTEND_URL', 'https://pnec-review.invalid')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:////tmp/pnec-synthetic-test.db')


@pytest.mark.parametrize('secret', ['', 'short', 'a' * 64, 'dev-secret-key-change-in-prod' * 2, 'example-development-key-' * 3, '0123456789abcdef' * 4])
def test_production_rejects_weak_signing_key(production_environment, monkeypatch, secret):
    monkeypatch.setenv('SECRET_KEY', secret)
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        configure_production({})


def test_production_accepts_explicit_persistent_database(production_environment):
    config = {'SECURITY_STATE_PATH': '/tmp/pnec-test-limits.json'}
    configure_production(config)
    assert config['SQLALCHEMY_DATABASE_URI'].database == '/tmp/pnec-synthetic-test.db'
    assert config['BEARER_TOKEN_MAX_AGE'] == 86400


@pytest.mark.parametrize('url', ['http://pnec-review.invalid', 'https://evil.example', 'https://pnec-review.invalid.evil.example', 'https://pnec-review.invalid/path', 'https://contact@example.test', ''])
def test_production_rejects_unapproved_frontend(production_environment, monkeypatch, url):
    monkeypatch.setenv('FRONTEND_URL', url)
    with pytest.raises(RuntimeError, match='FRONTEND_URL'):
        configure_production({})


@pytest.mark.parametrize('database', ['', 'sqlite:///:memory:', 'sqlite:///relative.db', 'mysql+pymysql://localhost/pnec', 'not-a-url'])
def test_production_rejects_implicit_or_invalid_database(production_environment, monkeypatch, database):
    monkeypatch.setenv('DATABASE_URL', database)
    with pytest.raises(RuntimeError, match='database|DATABASE_URL'):
        configure_production({})


def test_partial_mysql_rejected_and_password_escaped(production_environment, monkeypatch):
    monkeypatch.delenv('DATABASE_URL')
    monkeypatch.setenv('DB_ENDPOINT', 'database.internal')
    with pytest.raises(RuntimeError, match='incomplete'):
        configure_production({})
    monkeypatch.setenv('DB_USERNAME', 'synthetic-user')
    monkeypatch.setenv('DB_PASSWORD', 'synthetic@:/password')
    config = {'SECURITY_STATE_PATH': '/tmp/pnec-test-limits.json'}
    configure_production(config)
    assert config['SQLALCHEMY_DATABASE_URI'].password == 'synthetic@:/password'


@pytest.mark.parametrize('ttl', ['0', '-1', '2592001', 'never'])
def test_invalid_production_token_policy(production_environment, monkeypatch, ttl):
    monkeypatch.setenv('BEARER_TOKEN_MAX_AGE', ttl)
    with pytest.raises(RuntimeError, match='BEARER_TOKEN_MAX_AGE'):
        configure_production({})


def test_invalid_environment_fails_closed(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'prodution')
    with pytest.raises(RuntimeError, match='FLASK_ENV'):
        get_config()
    monkeypatch.delenv('FLASK_ENV')
    assert get_config().DEBUG is True


def test_token_expiry_future_legacy_and_rotation(app, monkeypatch):
    user = User.query.filter_by(role='admin').first()
    now = int(time.time())
    monkeypatch.setattr('app.models.user.time.time', lambda: now)
    token = user.generate_token()
    db.session.commit()
    assert len(token) == 64
    client = app.test_client()
    headers = {'Authorization': 'Bearer ' + token}
    initial = client.get('/api/auth/me', headers=headers)
    assert initial.status_code == 200
    assert not initial.headers.getlist('Set-Cookie')
    assert client.get('/api/auth/me').status_code == 401
    monkeypatch.setattr('app.models.user.time.time', lambda: now + app.config['BEARER_TOKEN_MAX_AGE'])
    assert client.get('/api/auth/me', headers=headers).status_code == 401
    monkeypatch.setattr('app.models.user.time.time', lambda: now - 1)
    assert client.get('/api/auth/me', headers=headers).status_code == 401
    monkeypatch.setattr('app.models.user.time.time', lambda: now)
    tampered = token[:10] + secrets.token_hex(27)
    assert client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + tampered}).status_code == 401
    legacy = secrets.token_hex(32)
    user.auth_token = legacy
    db.session.commit()
    assert client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + legacy}).status_code == 401
    user.generate_token()
    db.session.commit()
    assert client.get('/api/auth/me', headers=headers).status_code == 401


def test_expiry_does_not_fall_back_to_cookie(app, admin_client):
    expired = 'p1' + format(int(time.time()) - 90000, '08x') + secrets.token_hex(27)
    assert admin_client.get('/api/questions', headers={'Authorization': 'Bearer ' + expired}).status_code == 401


@pytest.mark.parametrize('content_type', ['application/x-www-form-urlencoded', 'multipart/form-data'])
def test_cookie_forms_and_multipart_require_csrf(app, admin_client, content_type):
    app.config['CSRF_PROTECTION_ENABLED'] = True
    assert admin_client.post('/api/media', data={'title': 'Synthetic'}, content_type=content_type).status_code == 403
    assert admin_client.post('/api/media', data={'title': 'Synthetic'}, content_type=content_type, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert admin_client.post('/api/media', data={}, content_type=content_type, headers={'Origin': 'https://pnec-review.invalid'}).status_code == 400
    csrf = admin_client.get('/api/auth/csrf')
    assert csrf.headers['Cache-Control'] == 'no-store'
    assert admin_client.post('/api/media', data={'_csrf_token': csrf.json['csrf_token']}, content_type=content_type).status_code == 400


def test_csrf_header_is_session_bound_and_cors_preflight(app, admin_client):
    app.config['CSRF_PROTECTION_ENABLED'] = True
    token = admin_client.get('/api/auth/csrf').json['csrf_token']
    assert admin_client.patch('/api/auth/profile', json={'bio': 'Safe'}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert admin_client.post('/api/media', data={'_csrf_token': '\u2603'}).status_code == 403
    assert admin_client.patch('/api/auth/profile', json={'bio': 'Safe'}, headers={'X-CSRF-Token': token}).status_code == 200
    preflight = admin_client.options('/api/auth/profile', headers={'Origin': 'https://pnec-review.invalid', 'Access-Control-Request-Method': 'PATCH', 'Access-Control-Request-Headers': 'X-CSRF-Token,Authorization'})
    assert preflight.headers['Access-Control-Allow-Origin'] == 'https://pnec-review.invalid'
    assert 'X-CSRF-Token' in preflight.headers['Access-Control-Allow-Headers']
    assert app.test_client().post('/api/auth/login', json={}, headers={'Origin': 'null'}).status_code == 403


@pytest.mark.parametrize('path', ['/api/admin/publish/health', '/api/volunteer/interests', '/api/security/events', '/api/blog?all=1'])
def test_shared_admin_password_and_session_role_are_not_credentials(app, path):
    app.config['GITHUB_TOKEN'] = None
    client = app.test_client()
    assert client.get(path, headers={'X-PNEC-Admin-Key': app.config['ADMIN_PASSWORD']}).status_code == 401
    with client.session_transaction() as session:
        session['role'] = session['user_role'] = 'admin'
    assert client.get(path).status_code == 401
    admin = User.query.filter_by(role='admin').first()
    token = admin.generate_token()
    db.session.commit()
    assert client.get(path, headers={'Authorization': 'Bearer ' + token}).status_code == 200


def limiter_worker(path, queue):
    application = Flask(__name__)
    application.config['SECURITY_STATE_PATH'] = path
    with application.app_context():
        queue.put(sum(not shared_limits.rate_limited('login', 'same-client', 8, 60) for _ in range(4)))


def test_five_workers_share_atomic_limit_and_restart_state(tmp_path):
    path = str(tmp_path / 'limits.json')
    context = multiprocessing.get_context('spawn')
    queue = context.Queue()
    processes = [context.Process(target=limiter_worker, args=(path, queue)) for _ in range(5)]
    for process in processes:
        process.start()
    allowed = sum(queue.get(timeout=30) for _ in processes)
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    assert allowed == 8
    assert os.stat(path).st_mode & 0o777 == 0o600
    application = Flask(__name__)
    application.config['SECURITY_STATE_PATH'] = path
    with application.app_context():
        assert shared_limits.rate_limited('login', 'same-client', 8, 60)


def test_shared_lockout_unlock_and_corrupt_state_fail_closed(app, tmp_path):
    app.config.update(RATE_LIMIT_STORAGE='file', SECURITY_STATE_PATH=str(tmp_path / 'limits.json'))
    from app.utils.security import record_login_failure, is_account_locked, record_login_success, currently_locked_emails
    for _ in range(5):
        record_login_failure('synthetic@example.test')
    assert is_account_locked('synthetic@example.test')[0]
    assert currently_locked_emails() == ['synthetic@example.test']
    record_login_success('synthetic@example.test')
    assert not is_account_locked('synthetic@example.test')[0]
    (tmp_path / 'limits.json').write_text('{corrupt')
    assert app.test_client().post('/api/auth/login', json={}).status_code == 503


def test_forwarded_headers_cannot_evade_shared_limit(app, tmp_path):
    app.config.update(RATE_LIMIT_STORAGE='file', SECURITY_STATE_PATH=str(tmp_path / 'limits.json'))
    client = app.test_client()
    for index in range(8):
        assert client.post('/api/auth/login', json={}, headers={'X-Forwarded-For': '192.0.2.' + str(index)}).status_code == 400
    assert client.post('/api/auth/login', json={}, headers={'X-Forwarded-For': '198.51.100.1'}).status_code == 429


def test_real_production_factory_cookies_cors_and_persistence(production_environment, monkeypatch, tmp_path):
    from app import create_app
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'persistent.db'))
    monkeypatch.setenv('SECURITY_STATE_PATH', str(tmp_path / 'limits.json'))
    application = create_app()
    # Production no longer mutates schema during worker construction.
    from flask_migrate import upgrade
    with application.app_context():
        upgrade(directory=str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'migrations'))
    assert not application.debug
    assert application.config['RATE_LIMIT_STORAGE'] == 'file'
    assert application.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
    client = application.test_client()
    response = client.post('/api/auth/register', base_url='https://api.pnec-review.invalid',
        headers={'Origin': 'https://pnec-review.invalid'}, json={
            'email': 'production-mode@example.test', 'password': 'synthetic-password-2026', 'display_name': 'Synthetic'})
    assert response.status_code == 201
    token = response.json['token']
    cookies = response.headers.getlist('Set-Cookie')
    assert cookies and all('Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie for cookie in cookies)
    allowed = client.options('/api/auth/profile', headers={'Origin': 'https://pnec-review.invalid', 'Access-Control-Request-Method': 'PATCH'})
    assert allowed.headers['Access-Control-Allow-Origin'] == 'https://pnec-review.invalid'
    denied = client.options('/api/auth/profile', headers={'Origin': 'http://localhost:4600', 'Access-Control-Request-Method': 'PATCH'})
    assert 'Access-Control-Allow-Origin' not in denied.headers
    assert client.post('/api/auth/logout', headers={'Origin': 'http://localhost:4600'}).status_code == 403
    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    restarted = create_app()
    assert restarted.test_client().get('/api/auth/me', headers={'Authorization': 'Bearer ' + token}).status_code == 200
    with restarted.app_context():
        assert User.query.filter_by(email='production-mode@example.test').count() == 1
        db.session.remove()
        db.engine.dispose()
