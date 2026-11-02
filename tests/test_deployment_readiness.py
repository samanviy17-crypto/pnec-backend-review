"""Offline production-origin, upload, publisher and failed-migration recovery checks."""
import importlib.util
import io
from pathlib import Path
import secrets
import sqlite3
import pytest
from flask_migrate import upgrade
from app import create_app, db
from app.config import configure_production
from app.services.github_publish_service import _config, GitHubPublishError
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def production(monkeypatch,tmp_path):
    for name in ('DB_ENDPOINT','DB_USERNAME','DB_PASSWORD','ALLOWED_FRONTEND_ORIGINS'):
        monkeypatch.delenv(name,raising=False)
    for name,value in {'FLASK_ENV':'production','EVENT_STORAGE_TIMEZONE':'UTC','SECRET_KEY':secrets.token_hex(32),'FRONTEND_URL':'https://pnec.opencodingsociety.com','DATABASE_URL':'sqlite:///'+str(tmp_path/'test.db'),'SECURITY_STATE_PATH':str(tmp_path/'limits.json'),'UPLOAD_FOLDER':str(tmp_path/'uploads')}.items():
        monkeypatch.setenv(name,value)
    application=create_app(initialize_database=False)
    with application.app_context():
        yield application
        db.session.remove();db.engine.dispose()


def test_documented_origin_and_exact_production_cors(production):
    client=production.test_client()
    for origin,allowed in [('https://pnec.opencodingsociety.com',True),('https://powaynec.com',False),('https://pnec.opencodingsociety.com.attacker.test',False),('http://127.0.0.1:4000',False)]:
        response=client.options('/api/auth/profile',headers={'Origin':origin,'Access-Control-Request-Method':'PATCH'})
        assert ('Access-Control-Allow-Origin' in response.headers)==allowed
    assert client.get('/api/ready').status_code==503
    upgrade(directory=str(ROOT/'migrations'))
    assert client.get('/api/ready').status_code==200
    assert client.post('/api/auth/login',json={},headers={'Origin':'https://powaynec.com'}).status_code==403


def test_explicit_custom_origin(production,monkeypatch):
    monkeypatch.setenv('ALLOWED_FRONTEND_ORIGINS','https://preview.example.test')
    monkeypatch.setenv('FRONTEND_URL','https://preview.example.test')
    config={'SECURITY_STATE_PATH':'/tmp/synthetic-limits'}
    configure_production(config)
    assert config['APPROVED_ORIGINS']==['https://preview.example.test']
    monkeypatch.setenv('FRONTEND_URL','https://preview.example.test/path')
    with pytest.raises(RuntimeError):configure_production(config)


def test_github_publish_explicit_opt_in_and_destination(app):
    app.config['GITHUB_TOKEN']='synthetic-only'
    with pytest.raises(GitHubPublishError):_config()
    app.config.update(GITHUB_PUBLISH_ENABLED=True,GITHUB_OWNER='',GITHUB_REPO='',GITHUB_BRANCH='main')
    with pytest.raises(GitHubPublishError):_config()
    app.config.update(GITHUB_OWNER='synthetic',GITHUB_REPO='review',GITHUB_BRANCH='review/theme')
    assert _config()[1:]==('synthetic','review','review/theme')


def test_html_disguised_as_media_rejected(app,admin_client,tmp_path):
    app.config['UPLOAD_FOLDER']=str(tmp_path/'uploads')
    for name,body in [('fake.png',b'<script>alert(1)</script>'),('fake.mp4',b'<html>')]:
        response=admin_client.post('/api/media',data={'title':'Synthetic','file':(io.BytesIO(body),name)})
        assert response.status_code==400
    assert not (tmp_path/'uploads').exists()


def test_restore_after_partial_migration_failure(tmp_path):
    spec=importlib.util.spec_from_file_location('snapshot',ROOT/'scripts/sqlite_snapshot.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=tmp_path/'before.db'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE residents (id INTEGER PRIMARY KEY, label TEXT)')
        conn.execute("INSERT INTO residents VALUES (1,'synthetic')")
    backup=tmp_path/'backup.db';before=module.snapshot(source,backup)
    with pytest.raises(sqlite3.OperationalError):
        with sqlite3.connect(source) as conn:
            conn.execute('ALTER TABLE residents ADD COLUMN new_column TEXT')
            conn.execute('THIS IS AN INJECTED MIGRATION FAILURE')
    restored=tmp_path/'restored.db';result=module.snapshot(backup,restored)
    assert result['table_counts']==before['table_counts']
    with sqlite3.connect(restored) as conn:
        assert [r[1] for r in conn.execute('PRAGMA table_info(residents)')]==['id','label']
        assert conn.execute('SELECT * FROM residents').fetchall()==[(1,'synthetic')]
    assert source.exists() and backup.exists()


def test_admin_form_login_uses_account_lockout_and_blocks_redirects(app,admin_client):
    from app.models.user import User
    from app.utils.security import record_login_failure, record_login_success
    admin=User.query.filter_by(role='admin').first()
    response=admin_client.get('/api/admin/login?next=https://attacker.example/')
    assert response.status_code==302
    assert response.headers['Location'].startswith('/api/admin/')
    guest=app.test_client()
    for _ in range(5):record_login_failure(admin.email)
    assert guest.post('/api/admin/login',data={'email':admin.email,'password':'test-only-admin-password-2026'}).status_code==423
    record_login_success(admin.email)


def test_admin_get_logout_keeps_session(app,admin_client):
    assert admin_client.get('/api/admin/logout').status_code==200
    assert admin_client.get('/api/auth/me').status_code==200


def test_image_chat_never_silently_uses_text_only_provider(app,monkeypatch):
    from app.services import chat_service
    app.config.update(GROQ_API_KEY='synthetic-only',GEMINI_API_KEY=None)
    monkeypatch.setattr(chat_service,'_call_groq',lambda *a:pytest.fail('Image sent to text-only provider'))
    _,error=chat_service.generate_chat_response('Synthetic','Describe',image_data='synthetic-base64')
    assert error['code']=='IMAGE_PROVIDER_NOT_CONFIGURED'
    app.config['GEMINI_API_KEY']='synthetic-only'
    monkeypatch.setattr(chat_service,'_call_gemini',lambda *a:('Synthetic answer',None))
    assert chat_service.generate_chat_response('Synthetic','Describe',image_data='synthetic-base64')==('Synthetic answer',None)


def test_backend_root_is_pnec_service_discovery(client):
    response=client.get('/')
    assert response.status_code==200
    assert response.json=={'service':'PNEC API','health':'/api/health','readiness':'/api/ready'}


def test_fresh_public_contact_configuration_reaches_faq(app,monkeypatch):
    from app.config import Config
    from app.models.faq import FaqItem
    monkeypatch.setattr(Config,'PUBLIC_CONTACT_EMAIL','public-contact@example.test')
    from app import create_app
    configured=create_app()
    with configured.app_context():
        answers=[r.answer for r in FaqItem.query]
        assert any('public-contact@example.test' in text for text in answers)
        assert all('contact@example.test' not in text.replace('public-contact@example.test','') for text in answers)
        db.session.remove();db.engine.dispose()
