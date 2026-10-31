"""Disposable release-schema, recovery and upload tests. No existing databases."""
import importlib.util
import io
from pathlib import Path
import sqlite3

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import upgrade, downgrade
from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import mysql

from app import create_app, db
from app.config import Config
from app.models.user import User

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = str(ROOT / 'migrations')


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///' + str(tmp_path / 'release.db'))
    monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'uploads'))
    application = create_app(initialize_database=False)
    application.config.update(TESTING=True)
    with application.app_context():
        yield application
        db.session.remove()
        db.engine.dispose()


def test_worker_construction_does_not_initialize_schema(isolated):
    assert inspect(db.engine).get_table_names() == []
    assert isolated.test_client().get('/api/health').status_code == 200
    assert isolated.test_client().get('/api/ready').status_code == 503
    assert inspect(db.engine).get_table_names() == []


def test_frozen_migration_matches_release_and_repeats_safely(isolated):
    upgrade(directory=MIGRATIONS)
    assert isolated.test_client().get('/api/ready').status_code == 200
    with db.engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), db.metadata)
    assert differences == []
    assert len(inspect(db.engine).get_table_names()) == 29
    upgrade(directory=MIGRATIONS)
    assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() == '0001_pnec_release'


def test_existing_release_adoption_preserves_rows_and_refuses_destructive_downgrade(isolated):
    db.create_all()
    db.session.execute(text("INSERT INTO neighborhoods (name, number, zone) VALUES ('Synthetic', 99, 'A')"))
    db.session.commit()
    before = db.session.execute(text('SELECT * FROM neighborhoods')).fetchall()
    upgrade(directory=MIGRATIONS)
    assert db.session.execute(text('SELECT * FROM neighborhoods')).fetchall() == before
    with pytest.raises(SystemExit) as rejected:
        downgrade(directory=MIGRATIONS, revision='base')
    assert rejected.value.code == 1
    # Application rollback compatibility: original columns/rows remain queryable.
    assert db.session.execute(text('SELECT name, number, zone FROM neighborhoods')).fetchall() == [('Synthetic', 99, 'A')]
    assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() == '0001_pnec_release'


def test_known_legacy_nullable_profile_upgrade_retains_data(isolated):
    db.create_all()
    # A disposable pre-profile schema, never an existing personal database.
    db.session.execute(text('DROP INDEX ix_users_auth_token'))
    for name in ('bio', 'avatar_url', 'phone', 'auth_token'):
        db.session.execute(text('ALTER TABLE users DROP COLUMN ' + name))
    db.session.execute(text("INSERT INTO users (email, password_hash, display_name, role, is_active, created_at) VALUES ('legacy@example.test', 'synthetic-hash', 'Legacy', 'resident', 1, '2026-01-01')"))
    db.session.commit()
    upgrade(directory=MIGRATIONS)
    row = db.session.execute(text('SELECT email, bio, avatar_url, phone, auth_token FROM users')).one()
    assert tuple(row) == ('legacy@example.test', None, None, None, None)
    indexes = inspect(db.engine).get_indexes('users')
    assert any(i['column_names'] == ['auth_token'] and i['unique'] for i in indexes)
    assert db.session.execute(text('SELECT display_name FROM users')).scalar() == 'Legacy'


def test_unknown_schema_rejected_before_release_ddl(isolated):
    db.session.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)'))
    db.session.execute(text("INSERT INTO users VALUES (1, 'preserved@example.test')"))
    db.session.commit()
    with pytest.raises(SystemExit) as rejected:
        upgrade(directory=MIGRATIONS)
    assert rejected.value.code == 1
    assert db.session.execute(text('SELECT email FROM users')).scalar() == 'preserved@example.test'
    assert set(inspect(db.engine).get_table_names()) <= {'users', 'alembic_version'}


def test_explicit_seed_is_idempotent_and_gated(isolated):
    runner = isolated.test_cli_runner()
    assert runner.invoke(args=['release-seed']).exit_code != 0
    upgrade(directory=MIGRATIONS)
    assert runner.invoke(args=['release-seed', '--approved']).exit_code == 0
    count = db.session.execute(text('SELECT COUNT(*) FROM neighborhoods')).scalar()
    assert count > 0
    assert runner.invoke(args=['release-seed', '--approved']).exit_code == 0
    assert db.session.execute(text('SELECT COUNT(*) FROM neighborhoods')).scalar() == count


def test_mysql_create_ddl_compiles_for_release(isolated):
    # Static portability check only; no claim of executing against MySQL.
    for table in db.metadata.sorted_tables:
        assert str(CreateTable(table).compile(dialect=mysql.dialect()))


def test_sqlite_backup_restore_new_path_and_foreign_keys(tmp_path):
    spec = importlib.util.spec_from_file_location('sqlite_snapshot', ROOT / 'scripts/sqlite_snapshot.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / 'source.db'
    with sqlite3.connect(source) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE records (id INTEGER PRIMARY KEY, label TEXT)')
        connection.execute("INSERT INTO records VALUES (1, 'synthetic')")
        connection.commit()
        backup = tmp_path / 'backup.db'
        manifest = module.snapshot(source, backup)
    restored = tmp_path / 'restored.db'
    assert module.snapshot(backup, restored)['table_counts'] == manifest['table_counts']
    assert module.verify(restored) == {'records': 1}
    with pytest.raises(FileExistsError):
        module.snapshot(backup, restored)
    with sqlite3.connect(source) as connection:
        assert connection.execute('SELECT label FROM records').fetchone()[0] == 'synthetic'


def test_upload_collision_legacy_serving_and_traversal(app, admin_client, monkeypatch, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    fixed = 'a' * 32
    patch = monkeypatch.context()
    scoped = patch.__enter__()
    scoped.setattr('app.services.media_service.secrets.token_hex', lambda count: fixed)
    (tmp_path / (fixed + '.png')).write_bytes(b'preserved')
    response = admin_client.post('/api/media', data={'title': 'Collision', 'file': (io.BytesIO(b'new'), 'same.png')})
    assert response.status_code != 201
    assert (tmp_path / (fixed + '.png')).read_bytes() == b'preserved'
    patch.__exit__(None, None, None)
    first = admin_client.post('/api/media', data={'title': 'First', 'file': (io.BytesIO(b'first'), '../../same.png')})
    second = admin_client.post('/api/media', data={'title': 'Second', 'file': (io.BytesIO(b'second'), 'same.png')})
    assert first.status_code == second.status_code == 201
    urls = [r.json['post']['media_url'] for r in (first, second)]
    assert urls[0] != urls[1]
    for url, content in zip(urls, [b'first', b'second']):
        fetched = app.test_client().get(url)
        assert fetched.status_code == 200 and fetched.data == content
        assert fetched.headers['X-Content-Type-Options'] == 'nosniff'
        assert fetched.headers['Content-Disposition'].startswith('attachment')
    (tmp_path / 'legacy.png').write_bytes(b'legacy')
    assert app.test_client().get('/static/uploads/legacy.png').data == b'legacy'
    assert app.test_client().get('/static/uploads/../hidden.env').status_code == 404
    assert app.test_client().get('/static/uploads/.env').status_code == 404


def test_uploaded_file_and_database_survive_worker_restart(isolated):
    from werkzeug.security import generate_password_hash
    upgrade(directory=MIGRATIONS)
    user = User(email='media@example.test', display_name='Synthetic', role='admin',
                password_hash=generate_password_hash('synthetic-test-password'))
    token = user.generate_token()
    db.session.add(user)
    db.session.commit()
    headers = {'Authorization': 'Bearer ' + token, 'Origin': 'https://pnec-review.invalid'}
    response = isolated.test_client().post('/api/media', headers=headers,
        data={'title': 'Persisted', 'file': (io.BytesIO(b'persisted-image'), 'test.png')})
    assert response.status_code == 201
    url = response.json['post']['media_url']
    db.session.remove()
    db.engine.dispose()
    restarted = create_app(initialize_database=False)
    restarted.config['TESTING'] = True
    client = restarted.test_client()
    assert client.get(url).data == b'persisted-image'
    assert client.get('/api/media').json['posts'][0]['media_url'] == url
    assert client.get('/api/ready').status_code == 200
    with restarted.app_context():
        db.session.remove()
        db.engine.dispose()
