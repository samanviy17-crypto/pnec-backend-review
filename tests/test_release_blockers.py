"""Regression coverage for the independent review; disposable/synthetic data only."""
import base64
import importlib.util
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from flask_migrate import upgrade
from PIL import Image
from sqlalchemy import text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.config import Config
from app.models.event import Event
from app.models.media import MediaPost
from app.models.neighborhood import Neighborhood
from app.models.user import User
from app.models.operations import ResidentCheckIn

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bearer(user):
    user.generate_token()
    db.session.commit()
    return {'Authorization': 'Bearer ' + user.auth_token}


def test_coordinator_residence_cannot_change_assigned_scope(app):
    first, second = Neighborhood.query.limit(2).all()
    coordinator = User(email='coordinator-review@example.test', display_name='Synthetic coordinator',
                       role='coordinator', neighborhood_id=first.id, password_hash='unused')
    resident = User(email='resident-review@example.test', display_name='Synthetic resident',
                    role='resident', neighborhood_id=second.id, password_hash='unused')
    db.session.add_all([coordinator, resident]); db.session.commit()
    db.session.add(ResidentCheckIn(user_id=resident.id, neighborhood_id=second.id, status='safe'))
    db.session.commit()
    app.config['COORDINATOR_ASSIGNMENTS'] = {str(coordinator.id): first.id}
    headers = bearer(coordinator)
    client = app.test_client()
    assert client.get('/api/check-ins', headers=headers).json['check_ins'] == []
    assert client.patch('/api/auth/profile', headers=headers, json={'neighborhood_id': second.id}).status_code == 200
    assert client.get('/api/check-ins', headers=headers).json['check_ins'] == []
    data = {'title': 'Synthetic shift', 'neighborhood_id': second.id, 'description': '',
            'capacity': 2, 'starts_at': (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
    assert client.post('/api/volunteer/tasks', headers=headers, json=data).status_code == 403
    data['neighborhood_id'] = first.id
    made = client.post('/api/volunteer/tasks', headers=headers, json=data)
    assert made.status_code == 201
    # Changing residence never grants access to other coordinators' rosters.
    assert 'volunteers' in client.get('/api/volunteer/tasks', headers=headers).json['tasks'][0]
    app.config['COORDINATOR_ASSIGNMENTS'] = {}
    assert 'volunteers' not in client.get('/api/volunteer/tasks', headers=headers).json['tasks'][0]
    assert client.patch('/api/volunteer/tasks/'+str(made.json['id']), headers=headers,
                        json={'closed': True}).status_code == 403
    assert client.patch('/api/auth/profile', headers=headers,
                        json={'COORDINATOR_ASSIGNMENTS': {str(coordinator.id): second.id}}).status_code == 400
    app.config['COORDINATOR_ASSIGNMENTS'] = {str(coordinator.id): second.id}
    assert len(client.get('/api/check-ins', headers=headers).json['check_ins']) == 1


@pytest.mark.parametrize('raw', ['[]', '{"1":true}', '{"1":"2"}', '{"0":1}', 'invalid'])
def test_malformed_assignment_config_fails_closed(app, monkeypatch, raw):
    from app.utils.release_policy import configure_release_policy
    monkeypatch.setenv('COORDINATOR_ASSIGNMENTS', raw)
    with pytest.raises(RuntimeError):
        configure_release_policy(app)


def test_event_delete_preserves_gallery_and_integrity(app, admin_client):
    event = Event(title='Synthetic event', date=datetime(2030, 1, 1))
    db.session.add(event); db.session.commit()
    post = MediaPost(title='Synthetic gallery', media_url='/static/uploads/synthetic.png', event_id=event.id)
    db.session.add(post); db.session.commit()
    assert db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
    assert admin_client.delete(f'/api/events/{event.id}').status_code == 409
    assert db.session.get(MediaPost, post.id).event_id == event.id
    assert db.session.get(Event, event.id) is not None
    assert db.session.execute(text('PRAGMA foreign_key_check')).fetchall() == []
    # Existing explicitly approved metadata unlink allows deletion; no image is deleted.
    post.event_id = None; db.session.commit()
    assert admin_client.delete(f'/api/events/{event.id}').status_code == 200
    assert db.session.get(MediaPost, post.id) is not None
    db.session.add(MediaPost(title='Orphan rejected', media_url='/synthetic.png', event_id=999999))
    with pytest.raises(IntegrityError): db.session.commit()
    db.session.rollback()
    assert db.session.execute(text('PRAGMA foreign_key_check')).fetchall() == []


def test_event_delete_file_database_backup_restore_and_reconnect(tmp_path, monkeypatch):
    path = tmp_path/'synthetic.db'
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///'+str(path))
    monkeypatch.setattr(Config, 'ADMIN_PASSWORD', '')
    app = create_app()
    app.config.update(TESTING=True, CSRF_PROTECTION_ENABLED=False, EVENT_STORAGE_TIMEZONE='UTC')
    with app.app_context():
        admin = User(email='backup-review@example.test', display_name='Synthetic admin', role='admin', password_hash='unused')
        db.session.add(admin); db.session.commit(); headers = bearer(admin)
        event = Event(title='Retained event', date=datetime(2030, 1, 1)); db.session.add(event); db.session.commit()
        post = MediaPost(title='Retained image', media_url='/synthetic.png', event_id=event.id)
        db.session.add(post); db.session.commit()
        client = app.test_client()
        assert client.delete(f'/api/events/{event.id}', headers=headers).status_code == 409
        snapshot = load('scripts/sqlite_snapshot.py', 'event_snapshot')
        before = snapshot.snapshot(path, tmp_path/'backup.db')
        restored = snapshot.snapshot(tmp_path/'backup.db', tmp_path/'restored.db')
        assert before['table_counts'] == restored['table_counts']
        assert restored['table_counts']['media_posts'] == 1
        post.event_id = None; db.session.commit()
        assert client.delete(f'/api/events/{event.id}', headers=headers).status_code == 200
        snapshot.snapshot(path, tmp_path/'after-delete.db')
        db.session.remove(); db.engine.dispose()
        assert db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
        assert db.session.execute(text('PRAGMA foreign_key_check')).fetchall() == []
        db.session.remove(); db.engine.dispose()


def test_event_timezone_create_update_offset_normalization(app, admin_client):
    result = admin_client.post('/api/events', json={'title': 'Offset event', 'date': '2030-11-10T18:00:00-08:00'})
    assert result.status_code == 201
    item = result.json['event']; assert item['date'] == '2030-11-11T02:00:00Z'
    assert db.session.get(Event, item['id']).date == datetime(2030, 11, 11, 2)
    updated = admin_client.patch('/api/events/'+str(item['id']), json={'date': '2030-11-11T08:00:00+05:30'})
    assert updated.json['event']['date'] == '2030-11-11T02:30:00Z'
    assert admin_client.post('/api/events', json={'title': 'Naive rejected', 'date': '2030-11-11T02:00:00'}).status_code == 400


def test_legacy_timezone_preserved_and_ambiguity_blocks(app, admin_client):
    event = Event(title='Legacy unchanged', date=datetime(2030, 11, 10, 18))
    db.session.add(event); db.session.commit()
    app.config['EVENT_STORAGE_TIMEZONE'] = None
    assert admin_client.get('/api/events').status_code == 503
    app.config['EVENT_STORAGE_TIMEZONE'] = 'America/Los_Angeles'
    assert event.to_dict()['date'] == '2030-11-11T02:00:00Z'
    assert event.date == datetime(2030, 11, 10, 18)
    response = admin_client.post('/api/events', json={'title': 'New compatible event', 'date': '2030-11-12T02:00:00Z'})
    assert response.status_code == 201
    assert db.session.get(Event, response.json['event']['id']).date == datetime(2030, 11, 11, 18)
    for date in [datetime(2026, 11, 1, 1, 30), datetime(2026, 3, 8, 2, 30)]:
        event.date = date; db.session.commit()
        assert admin_client.get('/api/events/calendar?year=2026&month=11').status_code == 503
        assert event.date == date


def test_calendar_exclusive_month_boundary_and_utc_filter(app):
    from app.services.events_service import events_between, get_events_for_month
    db.session.add_all([Event(title='Previous month', date=datetime(2030, 10, 31, 23, 59, 59, 999999)),
                        Event(title='Last microsecond', date=datetime(2030, 11, 30, 23, 59, 59, 999999)),
                        Event(title='Next month', date=datetime(2030, 12, 1))]); db.session.commit()
    assert [e['title'] for e in get_events_for_month(2030, 11, 'UTC')] == ['Last microsecond']
    assert [e['title'] for e in events_between(datetime(2030, 12, 1, tzinfo=timezone.utc))] == ['Next month']


@pytest.mark.parametrize('payload', [None, [], [1], 'string', 1, True, {'title': 42, 'date':'2030-01-01T00:00:00Z'},
    {'title':'x'*201, 'date':'2030-01-01T00:00:00Z'}, {'title':'x','date':[]},
    {'title':'x','date':'2030-01-01T00:00:00Z','image_url':'javascript:alert(1)'},
    {'title':'x','date':'2030-01-01T00:00:00Z','unknown':True}])
def test_event_malformed_create_is_controlled_400(admin_client, payload):
    assert admin_client.post('/api/events', json=payload).status_code == 400


@pytest.mark.parametrize('payload', [[1], {'title':42}, {'description':[]}, {'location':False}, {'date':None}, {'image_url':{}}])
def test_event_update_rejection_is_atomic(app, admin_client, payload):
    event = Event(title='Unchanged', date=datetime(2030,1,1)); db.session.add(event); db.session.commit()
    assert admin_client.patch('/api/events/'+str(event.id), json=payload).status_code == 400
    assert event.title == 'Unchanged' and event.date == datetime(2030,1,1)


@pytest.mark.parametrize('query', ['month=13', 'month=0', 'month=-1', 'month=x', 'year=0', 'year=10000'])
def test_calendar_invalid_query_400(client, query):
    assert client.get('/api/events/calendar?'+query).status_code == 400


@pytest.mark.parametrize('payload', [[1], None, 3, {'name': 42}, {'name':'Synthetic', 'email':[], 'role':'other'},
    {'name':'Synthetic', 'email':'s@example.test', 'role':{}},
    {'name':'Synthetic', 'email':'s@example.test', 'role':'other', 'neighborhood':'x'*121}])
def test_volunteer_bad_types_400(client, payload):
    assert client.post('/api/volunteer/submit', json=payload).status_code == 400


@pytest.mark.parametrize('query', ['limit=bad', 'limit=0', 'limit=-1', 'limit=501', 'status=bad', 'role=bad'])
def test_volunteer_bad_queries_400(admin_client, query):
    assert admin_client.get('/api/volunteer/interests?'+query).status_code == 400


def photo(size=(32,32), image_format='PNG'):
    image = Image.new('RGB', size, '#123456'); output = BytesIO(); image.save(output, format=image_format)
    return 'data:image/'+image_format.lower().replace('jpg','jpeg')+';base64,'+base64.b64encode(output.getvalue()).decode()


def test_avatar_valid_canonical_photo_persists_with_text_budget(app, admin_client):
    result = admin_client.patch('/api/auth/profile', json={'avatar_url':photo()})
    assert result.status_code == 200
    saved = result.json['user']['avatar_url']
    assert saved.startswith('data:image/jpeg;base64,') and len(saved.encode()) <= 60000
    assert admin_client.get('/api/auth/me').json['user']['avatar_url'] == saved
    assert str(User.__table__.c.avatar_url.type.compile(dialect=mysql.dialect())) == 'TEXT'


@pytest.mark.parametrize('value', ['https://example.test/a.jpg', 'javascript:alert(1)',
    'data:image/svg+xml;base64,PHN2Zy8+', 'data:image/jpeg;base64,bm90LWFuLWltYWdl',
    'data:image/jpeg;base64,'+'A'*60000, 'data:image/png;base64,!!!!'])
def test_avatar_invalid_rejected_atomically(app, admin_client, value):
    original = admin_client.get('/api/auth/me').json['user']['display_name']
    assert admin_client.patch('/api/auth/profile', json={'display_name':'Must not persist','avatar_url':value}).status_code == 400
    assert admin_client.get('/api/auth/me').json['user']['display_name'] == original


def test_avatar_excess_dimensions_rejected(admin_client):
    assert admin_client.patch('/api/auth/profile',json={'avatar_url':photo((401, 1))}).status_code == 400


@pytest.fixture
def schema(monkeypatch, tmp_path):
    monkeypatch.setattr(Config,'SQLALCHEMY_DATABASE_URI','sqlite:///'+str(tmp_path/'schema.db'))
    app=create_app(initialize_database=False)
    with app.app_context():
        yield app
        db.session.remove(); db.engine.dispose()


@pytest.mark.parametrize('value,valid', [(1,True),(0,True),(2,False)])
def test_boolean_integer_adoption_validates_rows_before_ddl(schema, value, valid):
    upgrade(directory=str(ROOT/'migrations'), revision='0001_pnec_release')
    # Existing compatible INTEGER-backed Boolean; no blind stamp/create_all.
    db.session.execute(text('CREATE TABLE announcements (id INTEGER NOT NULL PRIMARY KEY, message TEXT NOT NULL, level VARCHAR(20) NOT NULL, is_active INTEGER NOT NULL, expires_at DATETIME, created_by INTEGER REFERENCES users(id), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)'))
    db.session.execute(text("INSERT INTO announcements VALUES(1, 'synthetic', 'info', :value, NULL, NULL, '2030-01-01', '2030-01-01')"), {'value':value}); db.session.commit()
    if valid:
        upgrade(directory=str(ROOT/'migrations'))
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() == '0002_pnec_features'
    else:
        with pytest.raises(SystemExit): upgrade(directory=str(ROOT/'migrations'))
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() == '0001_pnec_release'
        assert 'chat_sessions' not in __import__('sqlalchemy').inspect(db.engine).get_table_names()
    assert db.session.execute(text('SELECT is_active FROM announcements')).scalar() == value


def test_mysql_boolean_reflection_policy():
    module=load('migrations/versions/0002_pnec_features.py','boolean_migration')
    import sqlalchemy as sa
    assert module.compatible_boolean_type(mysql.TINYINT(display_width=1), 'mysql')
    assert module.compatible_boolean_type(mysql.TINYINT(), 'mysql')
    assert not module.compatible_boolean_type(mysql.TINYINT(display_width=4), 'mysql')
    assert not module.compatible_boolean_type(sa.Integer(), 'mysql')
    assert not module.compatible_boolean_type(sa.String(1), 'sqlite')


def test_unassigned_coordinator_never_sees_citywide_roster(app):
    from app.models.operations import VolunteerTask, TaskSignup
    from app.routes.preparedness import task_dict
    from flask_login import login_user
    coordinator=User(email='unassigned-review@example.test',display_name='Synthetic',role='coordinator',password_hash='unused')
    db.session.add(coordinator); db.session.commit()
    task=VolunteerTask(title='Citywide', neighborhood_id=None, starts_at=datetime(2030,1,1), capacity=2, created_by=coordinator.id)
    db.session.add(task);db.session.commit()
    with app.test_request_context():
        login_user(coordinator)
        assert 'volunteers' not in task_dict(task)


def test_readiness_and_readonly_timestamp_audit(app):
    db.session.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'))
    db.session.execute(text("INSERT INTO alembic_version VALUES ('0002_pnec_features')"));db.session.commit()
    app.config['EVENT_STORAGE_TIMEZONE']=None
    assert app.test_client().get('/api/ready').status_code == 503
    app.config['EVENT_STORAGE_TIMEZONE']='America/Los_Angeles'
    event=Event(title='Review required',date=datetime(2026,11,1,1,30));db.session.add(event);db.session.commit()
    result=app.test_cli_runner().invoke(args=['release-event-audit'])
    assert result.exit_code != 0 and 'ambiguous/nonexistent stored times: 1' in result.output
    assert event.date==datetime(2026,11,1,1,30)
    app.config['EVENT_STORAGE_TIMEZONE']='UTC'
    assert app.test_cli_runner().invoke(args=['release-event-audit']).exit_code==0



def test_calendar_viewer_zone_at_month_boundary(app, client):
    event=Event(title='October evening', date=datetime(2030,11,1,2))
    db.session.add(event);db.session.commit()
    la=client.get('/api/events/calendar?year=2030&month=10&timezone=America/Los_Angeles')
    assert [e['title'] for e in la.json['events']] == ['October evening']
    utc=client.get('/api/events/calendar?year=2030&month=10&timezone=UTC')
    assert utc.json['events'] == []
    assert client.get('/api/events/calendar?year=2030&month=10&timezone=Invalid/Zone').status_code==400
    assert client.get('/api/events/calendar?year=2030&month=10&timezone=../../etc/passwd').status_code==400
