"""Production-host policy and additive announcement release; disposable SQLite only."""
from datetime import datetime
from pathlib import Path
import secrets
import pytest
from flask_migrate import upgrade
from sqlalchemy import text,inspect
from werkzeug.security import generate_password_hash
from app import create_app,db
from app.config import Config
from app.models.user import User
from app.models.announcement import Announcement
from app.release import REVISION

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='https://powaynec.opencodingsociety.com'
API='https://powaynec-api.opencodingsociety.com'

@pytest.fixture
def production(monkeypatch,tmp_path):
    for name in ['DB_ENDPOINT','DB_USERNAME','DB_PASSWORD','PNEC_REVIEW_EPHEMERAL']:
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('FLASK_ENV','production')
    monkeypatch.setenv('SECRET_KEY',secrets.token_urlsafe(48))
    monkeypatch.setenv('FRONTEND_URL',ORIGIN)
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(tmp_path/'production-test.db'))
    monkeypatch.setenv('SECURITY_STATE_PATH',str(tmp_path/'limits.json'))
    monkeypatch.setenv('UPLOAD_FOLDER',str(tmp_path/'uploads'))
    app=create_app(initialize_database=False)
    with app.app_context():
        upgrade(directory=str(ROOT/'migrations'))
        yield app
        db.session.remove();db.engine.dispose()


def test_production_cors_cookies_and_no_wildcard(production):
    app=production;assert app.config['APPROVED_ORIGINS']==[ORIGIN]
    assert app.config['SESSION_COOKIE_SECURE'] and app.config['SESSION_COOKIE_HTTPONLY']
    assert app.config['SESSION_COOKIE_SAMESITE']=='Lax'
    assert app.config['REMEMBER_COOKIE_SECURE'] and app.config['REMEMBER_COOKIE_HTTPONLY']
    assert app.config['REMEMBER_COOKIE_SAMESITE']=='Lax' and app.config['CSRF_PROTECTION_ENABLED']
    assert app.config['RATE_LIMIT_STORAGE']=='file' and app.config['AUTO_INITIALIZE_DATABASE'] is False
    c=app.test_client()
    for method in ['GET','HEAD','POST','PUT','PATCH','DELETE']:
        r=c.options('/api/auth/profile',base_url=API,headers={'Origin':ORIGIN,'Access-Control-Request-Method':method,'Access-Control-Request-Headers':'Authorization,Content-Type,X-CSRF-Token'})
        assert r.headers['Access-Control-Allow-Origin']==ORIGIN
        assert r.headers['Access-Control-Allow-Credentials']=='true'
        assert method in r.headers['Access-Control-Allow-Methods']
        assert 'x-csrf-token' in r.headers['Access-Control-Allow-Headers'].lower()
        assert len(r.headers.getlist('Access-Control-Allow-Origin'))==1
    for origin in ['http://powaynec.opencodingsociety.com',ORIGIN+'.attacker.example','https://powaynec.com','https://samanviy17-crypto.github.io','https://untrusted.example']:
        r=c.get('/api/health',base_url=API,headers={'Origin':origin})
        assert 'Access-Control-Allow-Origin' not in r.headers
        assert c.post('/api/auth/logout',base_url=API,headers={'Origin':origin}).status_code==403


def test_real_registration_cookie_csrf_and_announcement_roles(production):
    c=production.test_client();headers={'Origin':ORIGIN}
    assert c.post('/api/announcements',base_url=API,json={'message':'Denied anonymous'},headers=headers).status_code==401
    registered=c.post('/api/auth/register',base_url=API,json={'email':'production-test@example.test','display_name':'Synthetic Resident','password':secrets.token_urlsafe(24)},headers=headers)
    assert registered.status_code==201 and registered.json['user']['role']=='resident'
    cookie='; '.join(registered.headers.getlist('Set-Cookie'))
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    assert c.post('/api/announcements',base_url=API,json={'message':'Denied resident'},headers=headers).status_code==403
    assert c.patch('/api/auth/profile',base_url=API,json={'bio':'Rejected missing CSRF'}).status_code==403
    token=c.get('/api/auth/csrf',base_url=API).json['csrf_token']
    assert c.patch('/api/auth/profile',base_url=API,json={'bio':'Synthetic saved bio'},headers={'X-CSRF-Token':token}).status_code==200
    assert c.patch('/api/auth/profile',base_url=API,json={'role':'admin'},headers=headers).status_code==400
    password=secrets.token_urlsafe(24)
    db.session.add(User(email='production-admin@example.test',display_name='Synthetic Admin',role='admin',password_hash=generate_password_hash(password)));db.session.commit()
    assert c.post('/api/auth/login',base_url=API,json={'email':'production-admin@example.test','password':password},headers=headers).status_code==200
    r=c.post('/api/announcements',base_url=API,json={'message':'SYNTHETIC production-policy test','level':'info'},headers=headers)
    assert r.status_code==201
    assert c.get('/api/announcements',base_url=API).json['announcements'][0]['message']=='SYNTHETIC production-policy test'
    assert c.post('/api/announcements',base_url=API,json={'message':'Rejected origin'},headers={'Origin':'https://unapproved.example'}).status_code==403
    assert c.get('/api/auth/me',base_url=API,headers={'Authorization':'Bearer invalid'}).status_code==401
    assert c.post('/api/auth/logout',base_url=API,headers=headers).status_code==200
    assert c.get('/api/auth/me',base_url=API).status_code==401


def test_origin_validation_rejects_ephemeral_mode_and_near_misses(production,monkeypatch):
    monkeypatch.setenv('PNEC_REVIEW_EPHEMERAL','true')
    with pytest.raises(RuntimeError,match='ephemeral'):create_app(initialize_database=False)
    monkeypatch.delenv('PNEC_REVIEW_EPHEMERAL')
    for value in [ORIGIN+'.attacker.example',ORIGIN+'/path','http://powaynec.opencodingsociety.com',ORIGIN+':8443',ORIGIN+'?x=1']:
        monkeypatch.setenv('FRONTEND_URL',value)
        with pytest.raises(RuntimeError):create_app(initialize_database=False)


def test_old_revision_not_ready_then_additive_upgrade_preserves_data(monkeypatch,tmp_path):
    monkeypatch.setattr(Config,'SQLALCHEMY_DATABASE_URI','sqlite:///'+str(tmp_path/'old.db'))
    app=create_app(initialize_database=False)
    with app.app_context():
        upgrade(directory=str(ROOT/'migrations'),revision='0001_pnec_release')
        db.session.execute(text("INSERT INTO neighborhoods (name,number,zone) VALUES ('Synthetic retained',998,'B')"));db.session.commit()
        assert app.test_client().get('/api/ready').status_code==503
        upgrade(directory=str(ROOT/'migrations'))
        assert app.test_client().get('/api/ready').json['schema_revision']==REVISION
        assert db.session.execute(text('SELECT name FROM neighborhoods')).scalar()=='Synthetic retained'
        db.session.remove();db.engine.dispose()


def test_compatible_unversioned_announcement_adoption_preserves_rows(monkeypatch,tmp_path):
    monkeypatch.setattr(Config,'SQLALCHEMY_DATABASE_URI','sqlite:///'+str(tmp_path/'adopt.db'))
    app=create_app(initialize_database=False)
    with app.app_context():
        db.create_all()
        db.session.add(Announcement(id=47,message='SYNTHETIC retained notice',level='info',is_active=True));db.session.commit()
        before=db.session.execute(text('SELECT * FROM announcements')).fetchall()
        upgrade(directory=str(ROOT/'migrations'))
        assert db.session.execute(text('SELECT * FROM announcements')).fetchall()==before
        upgrade(directory=str(ROOT/'migrations'))
        assert app.test_client().get('/api/ready').status_code==200
        db.session.remove();db.engine.dispose()


def test_unknown_announcement_schema_stops_without_row_changes(monkeypatch,tmp_path):
    monkeypatch.setattr(Config,'SQLALCHEMY_DATABASE_URI','sqlite:///'+str(tmp_path/'drift.db'))
    app=create_app(initialize_database=False)
    with app.app_context():
        upgrade(directory=str(ROOT/'migrations'),revision='0001_pnec_release')
        db.session.execute(text('CREATE TABLE announcements (id INTEGER PRIMARY KEY, message TEXT)'))
        db.session.execute(text("INSERT INTO announcements VALUES (1,'Synthetic retained drift')"));db.session.commit()
        with pytest.raises(SystemExit):upgrade(directory=str(ROOT/'migrations'))
        assert db.session.execute(text('SELECT message FROM announcements')).scalar()=='Synthetic retained drift'
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0001_pnec_release'
        db.session.remove();db.engine.dispose()


def test_readiness_rejects_missing_table_despite_stamped_revision(production):
    db.session.execute(text('DROP TABLE announcements'));db.session.commit()
    response=production.test_client().get('/api/ready')
    assert response.status_code==503 and response.json=={'status':'not_ready'}


@pytest.mark.parametrize('change', ['wrong_length','unexpected_unique','missing_foreign_key'])
def test_legacy_table_constraints_are_checked_without_rewriting_rows(monkeypatch,tmp_path,change):
    monkeypatch.setattr(Config,'SQLALCHEMY_DATABASE_URI','sqlite:///'+str(tmp_path/'constraint.db'))
    app=create_app(initialize_database=False)
    with app.app_context():
        upgrade(directory=str(ROOT/'migrations'),revision='0001_pnec_release')
        level='VARCHAR(21)' if change=='wrong_length' else 'VARCHAR(20)'
        unique=' UNIQUE' if change=='unexpected_unique' else ''
        fk='' if change=='missing_foreign_key' else ', FOREIGN KEY(created_by) REFERENCES users(id)'
        db.session.execute(text(f'CREATE TABLE announcements (id INTEGER NOT NULL PRIMARY KEY, message TEXT NOT NULL{unique}, level {level} NOT NULL, is_active BOOLEAN NOT NULL, expires_at DATETIME, created_by INTEGER, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL{fk})'))
        db.session.execute(text("INSERT INTO announcements VALUES(9,'Synthetic retained','info',1,NULL,NULL,'2026-01-01','2026-01-01')"));db.session.commit()
        before=db.session.execute(text('SELECT * FROM announcements')).fetchall()
        with pytest.raises(SystemExit):upgrade(directory=str(ROOT/'migrations'))
        assert db.session.execute(text('SELECT * FROM announcements')).fetchall()==before
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0001_pnec_release'
        db.session.remove();db.engine.dispose()
