"""Account lifecycle, recovery mail, cookie and bearer regression tests."""
import re
import pytest
from app import db
from app.models.user import User
from app.routes.auth import _rate_buckets
from app.utils.security import _failed_attempts, _locked_until

@pytest.fixture(autouse=True)
def clear_limits():
    _rate_buckets.clear()
    _failed_attempts.clear()
    _locked_until.clear()


def register(app):
    with app.app_context():
        return app.test_client().post('/api/auth/register', json={
            'email':'auth@example.test', 'password':' original password ', 'display_name':'Resident'})


def api(app, method, path, **kwargs):
    with app.app_context():
        return app.test_client().open('/api/auth'+path, method=method, **kwargs)


def recovery_token(app):
    response=api(app,'POST','/forgot-password',json={'email':'auth@example.test'})
    assert response.status_code == 200 and 'token' not in response.json
    body=app.extensions['account_mail_outbox'][-1].body
    return re.search(r'token=([^\s]+)',body).group(1)


def test_login_bearer_roles_logout(app):
    created=register(app)
    assert created.status_code == 201
    token=created.json['token']
    assert api(app,'POST','/login',json={'email':'auth@example.test','password':'bad'}).status_code == 401
    signed=api(app,'POST','/login',json={'email':'AUTH@example.test','password':' original password ','remember':False})
    assert signed.status_code == 200
    token=signed.json['token']; headers={'Authorization':'Bearer '+token}
    assert api(app,'GET','/me',headers=headers).status_code == 200
    with app.app_context():
        assert app.test_client().get('/api/questions',headers=headers).status_code == 403
    assert api(app,'POST','/logout',headers=headers).status_code == 200
    assert api(app,'GET','/me',headers=headers).status_code == 401
    assert User.query.filter_by(email='auth@example.test').first().password_hash != ' original password '


def test_cookie_session_and_remember(app):
    register(app)
    with app.app_context():
        client=app.test_client()
        response=client.post('/api/auth/login',json={'email':'auth@example.test','password':' original password ','remember':False})
        assert response.status_code == 200
        assert not any(h.startswith('remember_token=') for h in response.headers.getlist('Set-Cookie'))
        assert client.get('/api/auth/me').status_code == 200
        saved_cookie = client.get_cookie('pnec_session').value
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/auth/me').status_code == 401
        client.set_cookie('pnec_session', saved_cookie)
        assert client.get('/api/auth/me').status_code == 401


def test_password_reset_and_reuse(app):
    created=register(app); old_token=created.json['token']
    token=recovery_token(app)
    response=api(app,'POST','/reset-password',json={'token':token,'password':'replacement-password'})
    assert response.status_code == 200
    assert api(app,'POST','/reset-password',json={'token':token,'password':'another-password'}).status_code == 400
    assert api(app,'GET','/me',headers={'Authorization':'Bearer '+old_token}).status_code == 401
    assert api(app,'POST','/login',json={'email':'auth@example.test','password':' original password '}).status_code == 401
    assert api(app,'POST','/login',json={'email':'auth@example.test','password':'replacement-password'}).status_code == 200


def test_invalid_expired_and_unknown_email(app):
    register(app); token=recovery_token(app)
    assert api(app,'POST','/reset-password',json={'token':'invalid','password':'replacement-password'}).status_code == 400
    app.config['PASSWORD_RESET_MAX_AGE']=-1
    assert api(app,'POST','/reset-password',json={'token':token,'password':'replacement-password'}).status_code == 400
    count=len(app.extensions['account_mail_outbox'])
    assert api(app,'POST','/forgot-password',json={'email':'unknown@example.test'}).status_code == 200
    assert len(app.extensions['account_mail_outbox']) == count


def test_reset_revokes_cookies(app):
    register(app)
    with app.app_context():
        client=app.test_client()
        client.post('/api/auth/login',json={'email':'auth@example.test','password':' original password ','remember':True})
        saved_cookie=client.get_cookie('pnec_session').value
    token=recovery_token(app)
    assert api(app,'POST','/reset-password',json={'token':token,'password':'replacement-password'}).status_code == 200
    with app.app_context():
        client.set_cookie('pnec_session',saved_cookie)
        assert client.get('/api/auth/me').status_code == 401


def test_registration_validation(app):
    assert api(app,'POST','/register',json={'email':'bad','password':'abcdefgh','display_name':'Resident'}).status_code == 400
    assert api(app,'POST','/register',json={'email':'x@example.test','password':'abcdefgh','display_name':'Resident','neighborhood_id':999999}).status_code == 400


def test_smtp_failure_does_not_disclose_account(app, monkeypatch):
    from app import mail
    register(app)
    app.config.update(TESTING=False, MAIL_DELIVERY='smtp')
    def failed_send(message):
        raise RuntimeError('simulated SMTP failure')
    monkeypatch.setattr(mail, 'send', failed_send)
    known=api(app,'POST','/forgot-password',json={'email':'auth@example.test'})
    unknown=api(app,'POST','/forgot-password',json={'email':'nobody@example.test'})
    assert known.status_code == unknown.status_code == 200
    assert known.json == unknown.json


def test_bearer_identity_overrides_other_cookie(app):
    register(app)
    resident=User.query.filter_by(email='auth@example.test').first()
    token=resident.auth_token
    admin=User.query.filter_by(role='admin').first()
    with app.app_context():
        client=app.test_client()
        with client.session_transaction() as session:
            session['_user_id']=admin.get_id()
            session['_fresh']=True
        response=client.get('/api/questions',headers={'Authorization':'Bearer '+token})
        assert response.status_code == 403
