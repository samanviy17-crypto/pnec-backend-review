"""Profile validation, ownership and persistence through the existing auth API."""
import pytest
from app import db, create_app
from app.config import Config
from app.models.user import User
from app.routes.auth import _rate_buckets


def request(app, method, path, **kwargs):
    with app.app_context():
        return app.test_client().open('/api/auth' + path, method=method, **kwargs)


def account(app, email='profile@example.test'):
    _rate_buckets.clear()
    result = request(app, 'POST', '/register', json={
        'display_name': 'Original Resident', 'email': email, 'password': 'profile-test-password'})
    assert result.status_code == 201
    return result.json, {'Authorization': 'Bearer ' + result.json['token']}


def test_profile_update_reload_and_new_email_login(app):
    created, headers = account(app)
    result = request(app, 'PATCH', '/profile', headers=headers, json={
        'display_name': 'Updated Resident', 'email': ' UPDATED@example.test ', 'phone': '+1 (858) 555-0100'})
    assert result.status_code == 200
    user = result.json['user']
    assert (user['display_name'], user['email'], user['phone']) == ('Updated Resident', 'updated@example.test', '+18585550100')
    assert not {'password', 'password_hash', 'auth_token'} & user.keys()
    assert request(app, 'GET', '/me', headers=headers).json['user'] == user
    db.session.remove()
    row = db.session.get(User, created['user']['id'])
    assert (row.display_name, row.email, row.phone) == ('Updated Resident', 'updated@example.test', '+18585550100')
    assert request(app, 'POST', '/logout', headers=headers).status_code == 200
    assert request(app, 'PATCH', '/profile', headers=headers, json={'display_name': 'Denied'}).status_code == 401
    assert request(app, 'POST', '/login', json={'email': 'profile@example.test', 'password': 'profile-test-password'}).status_code == 401
    signed = request(app, 'POST', '/login', json={'email': 'updated@example.test', 'password': 'profile-test-password'})
    assert signed.status_code == 200 and signed.json['user']['phone'] == '+18585550100'


@pytest.mark.parametrize('payload', [None, [], {'email': 'bad'}, {'phone': 'abc'}, {'phone': '12'},
    {'phone': '1'*16}, {'phone': 1234567890}, {'display_name': ''}, {'display_name': 'x'*101},
    {'bio': 'x'*501}, {'user_id': 1}, {'role': 'admin'}])
def test_invalid_profile_update_is_atomic(app, payload):
    created, headers = account(app)
    assert request(app, 'PATCH', '/profile', headers=headers, json=payload).status_code == 400
    assert request(app, 'GET', '/me', headers=headers).json['user'] == created['user']


def test_duplicate_email_and_ownership(app):
    first, headers = account(app)
    second, _ = account(app, 'other@example.test')
    result = request(app, 'PATCH', '/profile', headers=headers,
                     json={'display_name': 'Must not persist', 'email': 'OTHER@example.test'})
    assert result.status_code == 409
    assert request(app, 'GET', '/me', headers=headers).json['user'] == first['user']
    assert request(app, 'PATCH', '/profile', headers=headers,
                   json={'id': second['user']['id'], 'phone': '8585550100'}).status_code == 400
    assert db.session.get(User, second['user']['id']).phone is None
    assert request(app, 'PATCH', '/profile', json={'phone': '8585550100'}).status_code == 401


def test_cookie_profile_update_and_cors(app):
    account(app)
    with app.app_context():
        client = app.test_client()
        assert client.post('/api/auth/login', json={'email': 'profile@example.test',
                          'password': 'profile-test-password', 'remember': True}).status_code == 200
        result = client.patch('/api/auth/profile', json={'phone': ''}, headers={'Origin': 'http://127.0.0.1:4500'})
        assert result.status_code == 200
        assert result.headers['Access-Control-Allow-Origin'] == 'http://127.0.0.1:4500'
        assert result.headers['Access-Control-Allow-Credentials'] == 'true'
        assert client.get('/api/auth/me').json['user']['phone'] is None


def test_file_database_survives_app_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///' + str(tmp_path / 'profile.db'))
    monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
    first = create_app()
    first.config.update(TESTING=True)
    created, headers = account(first)
    assert request(first, 'PATCH', '/profile', headers=headers, json={
        'display_name': 'Persistent Resident', 'email': 'persistent@example.test', 'phone': '858-555-0100'}).status_code == 200
    with first.app_context():
        db.session.remove()
        db.engine.dispose()
    restarted = create_app()
    restarted.config.update(TESTING=True)
    user = request(restarted, 'GET', '/me', headers=headers).json['user']
    assert (user['id'], user['email'], user['phone']) == (created['user']['id'], 'persistent@example.test', '8585550100')


def test_duplicate_registration_and_invalid_token(app):
    account(app)
    duplicate = request(app, 'POST', '/register', json={
        'display_name': 'Duplicate', 'email': 'PROFILE@example.test', 'password': 'profile-test-password'})
    assert duplicate.status_code == 409
    assert User.query.filter_by(email='profile@example.test').count() == 1
    assert request(app, 'GET', '/me', headers={'Authorization': 'Bearer invalid-test-token'}).status_code == 401
    assert request(app, 'PATCH', '/profile', headers={'Authorization': 'Bearer invalid-test-token'},
                   json={'email': 'changed@example.test'}).status_code == 401
    with app.app_context():
        response = app.test_client().options('/api/auth/profile', headers={
            'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'PATCH'})
        assert 'Access-Control-Allow-Origin' not in response.headers
