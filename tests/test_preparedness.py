"""Exercise account persistence, neighborhood privacy and community workflows."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from app import db
from app.models.user import User
from app.models.neighborhood import Neighborhood


@pytest.fixture
def accounts(app):
    blocks = Neighborhood.query.limit(2).all()
    users = {}
    for name, role, nid in [('resident','resident',blocks[0].id), ('neighbor','resident',blocks[1].id),
        ('coordinator','coordinator',blocks[0].id), ('other_coordinator','coordinator',blocks[1].id),
        ('staff','staff',None), ('unassigned','resident',None)]:
        user = User(email=name+'@example.test', display_name=name, role=role,
                    password_hash='unused-test-hash', neighborhood_id=nid)
        user.generate_token(); db.session.add(user); users[name] = user
    db.session.commit()
    return users


def call(app, accounts, method, path, name='resident', data=None):
    with app.app_context():
        return app.test_client().open('/api'+path, method=method,
            headers={'Authorization':'Bearer '+accounts[name].auth_token}, json=data)


def test_household_persistence_and_privacy(app, accounts):
    data = {'items':{'water':True,'evacuation':True}, 'household_size':4,
            'meeting_point':'Library', 'evacuation_plan':'Review neighborhood map'}
    saved = call(app,accounts,'PATCH','/preparedness',data=data)
    assert saved.status_code == 200 and saved.json['progress'] == 9
    assert call(app,accounts,'GET','/preparedness').json['meeting_point'] == 'Library'
    assert call(app,accounts,'GET','/preparedness','neighbor').json['items'] == {}
    assert call(app,accounts,'PATCH','/preparedness',data={'items':{'water':False}}).json['items']['evacuation'] is True


@pytest.mark.parametrize('payload', [{'household_size':0}, {'household_size':True},
    {'items':{'water':'true'}}, {'items':{'unknown':True}}, {'items':[]},
    {'meeting_point':'x'*301}, {'evacuation_plan':23}])
def test_household_validation(app,accounts,payload):
    assert call(app,accounts,'PATCH','/preparedness',data=payload).status_code == 400


def test_quiz_score_and_recommendations(app,accounts):
    questions = app.test_client().get('/api/preparedness/quiz').json['questions']
    assert len(questions) == 10
    answers = {q['id']:False for q in questions}
    result = call(app,accounts,'POST','/preparedness/quiz',data={'answers':answers})
    assert result.json['score'] == 0 and len(result.json['recommendations']) == 3
    answers = {q['id']:True for q in questions}
    assert call(app,accounts,'POST','/preparedness/quiz',data={'answers':answers}).json['score'] == 100
    assert call(app,accounts,'GET','/preparedness').json['quiz_answers'] == answers
    assert call(app,accounts,'POST','/preparedness/quiz',data={'answers':{}}).status_code == 400


@pytest.mark.parametrize('ready_count', [0, 5, 10])
def test_quiz_mixed_scores_ordered_recommendations_and_reload(app, accounts, ready_count):
    from app.services.preparedness_service import QUIZ
    answers = {key: index < ready_count for index, (key, _, _) in enumerate(QUIZ)}
    response = call(app, accounts, 'POST', '/preparedness/quiz', data={'answers': answers})
    expected = {'score': ready_count * 10, 'recommendations': [q[2] for q in QUIZ[ready_count:]][:3]}
    assert response.status_code == 200 and response.json == expected
    reloaded = call(app, accounts, 'GET', '/preparedness').json
    assert reloaded['quiz_answers'] == answers and reloaded['assessment'] == expected


@pytest.mark.parametrize('bad_value', [0, 1, 'yes', 'false', None, [], {}])
def test_quiz_rejects_nonboolean_without_overwriting_saved_answers(app, accounts, bad_value):
    from app.services.preparedness_service import QUIZ
    valid = {key: True for key, _, _ in QUIZ}
    assert call(app, accounts, 'POST', '/preparedness/quiz', data={'answers': valid}).status_code == 200
    invalid = {**valid, QUIZ[0][0]: bad_value}
    assert call(app, accounts, 'POST', '/preparedness/quiz', data={'answers': invalid}).status_code == 400
    assert call(app, accounts, 'GET', '/preparedness').json['quiz_answers'] == valid


@pytest.mark.parametrize('change', ['missing', 'extra'])
def test_quiz_requires_exact_question_keys(app, accounts, change):
    from app.services.preparedness_service import QUIZ
    answers = {key: True for key, _, _ in QUIZ}
    if change == 'missing':
        answers.pop(QUIZ[0][0])
    else:
        answers['unknown'] = True
    assert call(app, accounts, 'POST', '/preparedness/quiz', data={'answers': answers}).status_code == 400


def test_parameterized_quiz_collection_limits_and_all_answer_combinations():
    from itertools import product
    from app.services.preparedness_service import QUIZ, evaluate_preparedness
    assert evaluate_preparedness({}, []) == {'score': 0, 'recommendations': []}
    custom = [('a', 'Question A', 'Action A'), ('b', 'Question B', 'Action B')]
    assert evaluate_preparedness({'a': True, 'unknown': True}, custom, 1) == {
        'score': 50, 'recommendations': ['Action B']}
    assert evaluate_preparedness({}, custom, 0) == {'score': 0, 'recommendations': []}
    for values in product([False, True], repeat=len(QUIZ)):
        answers = dict(zip((q[0] for q in QUIZ), values))
        result = evaluate_preparedness(answers, QUIZ)
        assert result['score'] == sum(values) * 10
        assert result['recommendations'] == [q[2] for q, ready in zip(QUIZ, values) if not ready][:3]


def task_data(accounts):
    return {'title':'Supply drive volunteers', 'description':'Meet at center',
        'starts_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
        'capacity':1, 'neighborhood_id':accounts['resident'].neighborhood_id}


def test_shifts_capacity_duplicate_claim_cancel_and_close(app,accounts):
    data = task_data(accounts)
    assert call(app,accounts,'POST','/volunteer/tasks',data=data).status_code == 403
    created = call(app,accounts,'POST','/volunteer/tasks','coordinator',data)
    assert created.status_code == 201
    tid = created.json['id']; path = f'/volunteer/tasks/{tid}/signup'
    assert call(app,accounts,'POST',path,data={}).json['claimed_count'] == 1
    assert call(app,accounts,'POST',path,data={}).json['claimed_count'] == 1
    assert call(app,accounts,'POST',path,'neighbor',{}).status_code == 409
    assert call(app,accounts,'DELETE',path).json['claimed_count'] == 0
    assert call(app,accounts,'POST',path,'neighbor',{}).status_code == 200
    assert call(app,accounts,'PATCH',f'/volunteer/tasks/{tid}','other_coordinator',{'closed':True}).status_code == 403
    call(app,accounts,'PATCH',f'/volunteer/tasks/{tid}','coordinator',{'closed':True})
    call(app,accounts,'DELETE',path,'neighbor')
    assert call(app,accounts,'POST',path,data={}).status_code == 409
    assert 'volunteers' not in app.test_client().get('/api/volunteer/tasks').json['tasks'][0]


def test_shift_neighborhood_and_date_validation(app,accounts):
    data = task_data(accounts); data['neighborhood_id'] = accounts['neighbor'].neighborhood_id
    assert call(app,accounts,'POST','/volunteer/tasks','coordinator',data).status_code == 403
    data['starts_at'] = '2020-01-01T00:00:00Z'
    assert call(app,accounts,'POST','/volunteer/tasks','staff',data).status_code == 400
    data['starts_at'] = '2030-01-01T00:00:00'
    assert call(app,accounts,'POST','/volunteer/tasks','staff',data).status_code == 400


def test_checkins_neighborhood_privacy_and_removal(app,accounts):
    for name in ['resident','neighbor']:
        response = call(app,accounts,'PUT','/check-ins',name,{'status':'need_help','note':'Check on me','neighborhood_id':-1})
        assert response.status_code == 200 and response.json['neighborhood_id'] == accounts[name].neighborhood_id
    assert len(call(app,accounts,'GET','/check-ins').json['check_ins']) == 1
    assert len(call(app,accounts,'GET','/check-ins','coordinator').json['check_ins']) == 1
    assert len(call(app,accounts,'GET','/check-ins','staff').json['check_ins']) == 2
    assert call(app,accounts,'PUT','/check-ins','unassigned',{'status':'safe'}).status_code == 400
    assert call(app,accounts,'PUT','/check-ins',data={'status':'unknown'}).status_code == 400
    assert call(app,accounts,'PUT','/check-ins',data={'status':'safe'}).json['status'] == 'safe'
    call(app,accounts,'DELETE','/check-ins')
    assert call(app,accounts,'GET','/check-ins').json['check_ins'] == []


def test_drives_confirmed_only_and_idempotent_receipt(app,accounts):
    data = {'title':'Water drive','description':'Drop off at center','unit':'bottles','goal':10}
    assert call(app,accounts,'POST','/supply-drives',data=data).status_code == 403
    drive = call(app,accounts,'POST','/supply-drives','staff',data); assert drive.status_code == 201
    did = drive.json['id']; path = f'/supply-drives/{did}/pledges'
    pledge = call(app,accounts,'POST',path,data={'quantity':4}); assert pledge.status_code == 201
    public = app.test_client().get('/api/supply-drives').json['drives'][0]
    assert public['received'] == 0 and public['pledged'] == 4 and public['progress'] == 0
    pid = pledge.json['id']; receipt = f'/supply-pledges/{pid}/receive'
    assert call(app,accounts,'PATCH',receipt,data={}).status_code == 403
    assert call(app,accounts,'PATCH',receipt,'staff',{}).json['received'] == 4
    assert call(app,accounts,'PATCH',receipt,'staff',{}).json['received'] == 4
    assert call(app,accounts,'GET',path,'neighbor').json['pledges'] == []
    call(app,accounts,'PATCH',f'/supply-drives/{did}','staff',{'closed':True})
    assert call(app,accounts,'POST',path,data={'quantity':4}).status_code == 409


def test_hazard_routing_permissions_and_status(app,accounts):
    data = {'category':'route','location':'Example street','description':'Blocked route',
            'neighborhood_id':accounts['neighbor'].neighborhood_id}
    report = call(app,accounts,'POST','/hazards',data=data); assert report.status_code == 201
    rid = report.json['id']
    assert call(app,accounts,'GET','/hazards','coordinator').json['hazards'] == []
    assert len(call(app,accounts,'GET','/hazards','other_coordinator').json['hazards']) == 1
    assert call(app,accounts,'GET','/hazards','neighbor').json['hazards'] == []
    assert call(app,accounts,'PATCH',f'/hazards/{rid}','coordinator',{'status':'resolved'}).status_code == 403
    assert call(app,accounts,'PATCH',f'/hazards/{rid}','other_coordinator',{'status':'resolved'}).json['status'] == 'resolved'
    data['neighborhood_id'] = 999999
    assert call(app,accounts,'POST','/hazards',data=data).status_code == 400


def test_faq_negative_and_repeat_votes(app,accounts):
    from app.models.faq import FaqItem
    item = FaqItem.query.first(); before = item.helpful_count
    path = f'/faq/helpful/{item.id}'
    assert call(app,accounts,'POST',path,data={'helpful':False}).status_code == 200
    assert call(app,accounts,'POST',path,data={'helpful':True}).json['helpful_count'] == before + 1
    assert call(app,accounts,'POST',path,data={'helpful':True}).json['helpful_count'] == before + 1
    assert call(app,accounts,'POST',path,data={'helpful':False}).json['helpful_count'] == before
    summary = call(app,accounts,'GET','/faq/feedback','staff').json['feedback'][0]
    assert summary['votes'] == 1 and summary['not_helpful'] == 1
    assert call(app,accounts,'POST',path,data={'helpful':'false'}).status_code == 400


def test_weekly_threat_content_events_and_offline(app,accounts,monkeypatch):
    from app.services import risk_service
    from app.models.event import Event
    monkeypatch.setattr(risk_service,'get_risk_assessment',lambda: {'fire_score':1,'heat_score':3,'flood_score':8,'is_stale':False})
    today = datetime.now(ZoneInfo('America/Los_Angeles')).date(); week = today-timedelta(days=today.weekday())
    data = {'title':'Flood prep','body':'Review flood resources.','week_start':week.isoformat(),'threat':'flood'}
    assert call(app,accounts,'POST','/preparedness/weekly',data=data).status_code == 403
    assert call(app,accounts,'POST','/preparedness/weekly','staff',data).status_code == 201
    db.session.add(Event(title='CERT class',date=datetime.utcnow()+timedelta(days=2),location='Center')); db.session.commit()
    response = app.test_client().get('/api/preparedness/weekly').json
    assert response['threat'] == 'flood' and response['tips'][0]['title'] == 'Flood prep'
    assert response['events'][0]['title'] == 'CERT class'
    def offline(): raise risk_service.RiskDataUnavailable('offline')
    monkeypatch.setattr(risk_service,'get_risk_assessment',offline)
    response = app.test_client().get('/api/preparedness/weekly').json
    assert not response['risk_available'] and response['threat'] == 'general'
    assert response['tips'][0]['threat'] == 'general'


@pytest.mark.parametrize('method,path', [('GET','/preparedness'),('PATCH','/preparedness'),
    ('POST','/preparedness/quiz'),('GET','/check-ins'),('PUT','/check-ins'),
    ('POST','/hazards'),('GET','/hazards'),('POST','/volunteer/tasks'),
    ('POST','/supply-drives'),('POST','/preparedness/weekly')])
def test_private_endpoints_require_auth(client,method,path):
    assert client.open('/api'+path,method=method,json={}).status_code == 401


def test_staff_question_bearer_association(app, accounts):
    from app.models.faq import UserQuestion
    from app.routes.faq import _qbuckets
    _qbuckets.clear()
    response = call(app, accounts, 'POST', '/questions/submit', data={
        'display_name': 'resident', 'email': 'resident@example.test',
        'question_text': 'How can we review our household evacuation plan?'})
    assert response.status_code == 201
    question = db.session.get(UserQuestion, response.json['question']['id'])
    assert question.user_id == accounts['resident'].id


def test_concurrent_faq_vote_changes(monkeypatch, tmp_path):
    """Separate connections race on one existing vote; retain legacy totals."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app import create_app
    from app.config import Config
    from app.models.faq import FaqItem, FaqFeedback
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///' + str(tmp_path / 'votes.db'))
    monkeypatch.setattr(Config, 'ADMIN_PASSWORD', 'test-only-admin-password-2026')
    concurrent_app = create_app()
    concurrent_app.config.update(TESTING=True)
    with concurrent_app.app_context():
        user = User.query.filter_by(role='admin').first()
        user.generate_token()
        token, uid = user.auth_token, user.id
        item = FaqItem.query.first()
        item_id, baseline = item.id, item.helpful_count
        db.session.add(FaqFeedback(item_id=item_id, voter_key='user:' + str(uid), helpful=False))
        db.session.commit()
    for helpful in (True, True, False, False, True):
        barrier = Barrier(4)
        def vote(_):
            barrier.wait(timeout=10)
            with concurrent_app.test_client() as client:
                return client.post(f'/api/faq/helpful/{item_id}',
                    headers={'Authorization': 'Bearer ' + token}, json={'helpful': helpful}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert list(pool.map(vote, range(4))) == [200] * 4
        with concurrent_app.app_context():
            assert db.session.get(FaqItem, item_id).helpful_count == baseline + int(helpful)
            assert FaqFeedback.query.filter_by(item_id=item_id).count() == 1
