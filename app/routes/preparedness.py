"""Account preparedness and community tools, using the existing database/auth."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, jsonify, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import BadRequest, HTTPException
from app import db
from app.models.operations import (VolunteerTask, TaskSignup, ResidentCheckIn,
    SupplyDrive, SupplyPledge, HazardReport, WeeklyTip)
from app.models.user import User
from app.models.event import Event
from app.services import preparedness_service as service
from app.utils.auth_decorators import requires_auth, requires_min_role

preparedness_bp = Blueprint('preparedness', __name__)


@preparedness_bp.errorhandler(HTTPException)
def validation_error(error):
    return jsonify({'message': error.description}), error.code


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest('A JSON object is required.')
    return data


@preparedness_bp.route('/preparedness', methods=['GET', 'PATCH'])
@requires_auth
def household():
    row = service.record_for(current_user)
    if request.method == 'PATCH':
        data = body()
        if 'items' in data:
            items = data['items']
            if not isinstance(items, dict) or any(k not in service.KIT_IDS or type(v) is not bool for k, v in items.items()):
                raise BadRequest('items must map checklist IDs to booleans.')
            row.items = {**(row.items or {}), **items}
        if 'household_size' in data:
            row.household_size = service.integer(data, 'household_size', 1, 50)
        for key, limit in [('meeting_point', 300), ('evacuation_plan', 2000)]:
            if key in data:
                setattr(row, key, service.string(data, key, limit))
        db.session.add(row)
        db.session.commit()
    return jsonify(service.household_dict(row))


@preparedness_bp.get('/preparedness/quiz')
def quiz_questions():
    return jsonify({'questions': [{'id': key, 'question': question} for key, question, _ in service.QUIZ]})


@preparedness_bp.post('/preparedness/quiz')
@requires_auth
def quiz_submit():
    answers = body().get('answers')
    if not isinstance(answers, dict) or set(answers) != {q[0] for q in service.QUIZ} or any(type(v) is not bool for v in answers.values()):
        raise BadRequest('Answer all ten questions with yes or no.')
    row = service.record_for(current_user)
    row.quiz_answers = answers
    db.session.add(row)
    db.session.commit()
    return jsonify(service.assessment(answers))


def task_dict(task):
    mine = current_user.is_authenticated and db.session.get(TaskSignup, (task.id, current_user.id)) is not None
    item = {'id': task.id, 'title': task.title, 'description': task.description,
            'neighborhood_id': task.neighborhood_id, 'starts_at': task.starts_at.isoformat() + 'Z',
            'capacity': task.capacity, 'claimed_count': task.claimed_count,
            'closed': task.closed, 'signed_up': bool(mine)}
    if current_user.is_authenticated and current_user.role in ('coordinator', 'staff', 'admin'):
        if current_user.role != 'coordinator' or current_user.neighborhood_id == task.neighborhood_id:
            item['volunteers'] = [{'name': u.display_name, 'email': u.email} for u in
                User.query.join(TaskSignup, TaskSignup.user_id == User.id).filter(TaskSignup.task_id == task.id).all()]
    return item


@preparedness_bp.get('/volunteer/tasks')
def tasks():
    return jsonify({'tasks': [task_dict(t) for t in VolunteerTask.query.order_by(VolunteerTask.starts_at).all()]})


@preparedness_bp.post('/volunteer/tasks')
@requires_min_role('coordinator')
def task_create():
    data = body()
    nid = service.neighborhood(data)
    service.manage_neighborhood(current_user, nid)
    task = VolunteerTask(title=service.string(data, 'title', 200, True),
        description=service.string(data, 'description', 2000), neighborhood_id=nid,
        starts_at=service.future_date(data), capacity=service.integer(data, 'capacity', 1, 1000),
        created_by=current_user.id)
    db.session.add(task)
    db.session.commit()
    return jsonify(task_dict(task)), 201


@preparedness_bp.patch('/volunteer/tasks/<int:task_id>')
@requires_min_role('coordinator')
def task_close(task_id):
    task = db.get_or_404(VolunteerTask, task_id)
    service.manage_neighborhood(current_user, task.neighborhood_id)
    data = body()
    if type(data.get('closed')) is not bool:
        raise BadRequest('closed must be a boolean.')
    task.closed = data['closed']
    db.session.commit()
    return jsonify(task_dict(task))


@preparedness_bp.route('/volunteer/tasks/<int:task_id>/signup', methods=['POST', 'DELETE'])
@requires_auth
def task_signup(task_id):
    db.get_or_404(VolunteerTask, task_id)
    existing = db.session.get(TaskSignup, (task_id, current_user.id))
    if request.method == 'DELETE':
        removed = TaskSignup.query.filter_by(task_id=task_id, user_id=current_user.id).delete()
        if removed:
            VolunteerTask.query.filter_by(id=task_id).update({'claimed_count': VolunteerTask.claimed_count - 1})
        db.session.commit()
    elif not existing:
        # Atomic capacity reservation prevents oversubscribing the final slot.
        reserved = VolunteerTask.query.filter(VolunteerTask.id == task_id,
            VolunteerTask.closed.is_(False), VolunteerTask.starts_at > datetime.utcnow(),
            VolunteerTask.claimed_count < VolunteerTask.capacity).update(
                {'claimed_count': VolunteerTask.claimed_count + 1})
        if not reserved:
            db.session.rollback()
            return jsonify({'message': 'This shift is full, closed, or already started.'}), 409
        db.session.add(TaskSignup(task_id=task_id, user_id=current_user.id))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({'message': 'You already claimed this shift. Refresh the board.'}), 409
    return jsonify(task_dict(db.session.get(VolunteerTask, task_id)))


def checkin_dict(row):
    user = db.session.get(User, row.user_id)
    return {'user_id': row.user_id, 'name': user.display_name, 'neighborhood_id': row.neighborhood_id,
            'status': row.status, 'note': row.note, 'updated_at': row.updated_at.isoformat() + 'Z'}


@preparedness_bp.route('/check-ins', methods=['GET', 'PUT', 'DELETE'])
@requires_auth
def check_ins():
    if request.method == 'GET':
        rows = service.scoped(ResidentCheckIn.query, ResidentCheckIn, current_user).order_by(ResidentCheckIn.updated_at.desc()).all()
        return jsonify({'check_ins': [checkin_dict(row) for row in rows]})
    row = db.session.get(ResidentCheckIn, current_user.id)
    if request.method == 'DELETE':
        if row:
            db.session.delete(row)
            db.session.commit()
        return jsonify({'ok': True})
    data = body()
    # Account neighborhood is authoritative; residents cannot post in another block.
    nid = current_user.neighborhood_id
    if nid is None:
        raise BadRequest('Set your neighborhood in your profile before checking in.')
    if data.get('status') not in ('safe', 'need_help'):
        raise BadRequest('Choose safe or need_help.')
    row = row or ResidentCheckIn(user_id=current_user.id)
    row.neighborhood_id = nid
    row.status = data['status']
    row.note = service.string(data, 'note', 1000)
    row.updated_at = datetime.utcnow()
    db.session.add(row)
    db.session.commit()
    return jsonify(checkin_dict(row))


def drive_dict(drive):
    pledged = db.session.query(db.func.coalesce(db.func.sum(SupplyPledge.quantity), 0)).filter_by(drive_id=drive.id, fulfilled=False).scalar()
    return {'id': drive.id, 'title': drive.title, 'description': drive.description,
            'unit': drive.unit, 'goal': drive.goal, 'received': drive.received,
            'pledged': pledged, 'closed': drive.closed,
            'progress': min(100, round(drive.received / drive.goal * 100))}


@preparedness_bp.get('/supply-drives')
def drives():
    return jsonify({'drives': [drive_dict(d) for d in SupplyDrive.query.order_by(SupplyDrive.id.desc()).all()]})


@preparedness_bp.post('/supply-drives')
@requires_min_role('staff')
def drive_create():
    data = body()
    drive = SupplyDrive(title=service.string(data, 'title', 200, True),
        description=service.string(data, 'description', 2000),
        unit=service.string(data, 'unit', 30, True), goal=service.integer(data, 'goal'))
    db.session.add(drive)
    db.session.commit()
    return jsonify(drive_dict(drive)), 201


@preparedness_bp.patch('/supply-drives/<int:drive_id>')
@requires_min_role('staff')
def drive_close(drive_id):
    drive = db.get_or_404(SupplyDrive, drive_id)
    data = body()
    if type(data.get('closed')) is not bool:
        raise BadRequest('closed must be a boolean.')
    drive.closed = data['closed']
    db.session.commit()
    return jsonify(drive_dict(drive))


@preparedness_bp.route('/supply-drives/<int:drive_id>/pledges', methods=['GET', 'POST'])
@requires_auth
def pledges(drive_id):
    drive = db.get_or_404(SupplyDrive, drive_id)
    if request.method == 'POST':
        quantity = service.integer(body(), 'quantity')
        # Serialize against closing the drive while pledging.
        available = SupplyDrive.query.filter_by(id=drive_id, closed=False).update({'received': SupplyDrive.received})
        if not available:
            db.session.rollback()
            return jsonify({'message': 'This drive is closed.'}), 409
        pledge = SupplyPledge(drive_id=drive_id, user_id=current_user.id, quantity=quantity)
        db.session.add(pledge)
        db.session.commit()
        return jsonify({'id': pledge.id, 'message': 'Pledge saved. Staff will confirm receipt after delivery.'}), 201
    query = SupplyPledge.query.filter_by(drive_id=drive_id)
    if current_user.role not in ('staff', 'admin'):
        query = query.filter_by(user_id=current_user.id)
    return jsonify({'pledges': [{'id': p.id, 'quantity': p.quantity, 'fulfilled': p.fulfilled,
        'name': db.session.get(User, p.user_id).display_name} for p in query.all()]})


@preparedness_bp.patch('/supply-pledges/<int:pledge_id>/receive')
@requires_min_role('staff')
def receive_pledge(pledge_id):
    pledge = db.get_or_404(SupplyPledge, pledge_id)
    updated = SupplyPledge.query.filter_by(id=pledge_id, fulfilled=False).update({'fulfilled': True})
    if updated:
        SupplyDrive.query.filter_by(id=pledge.drive_id).update({'received': SupplyDrive.received + pledge.quantity})
    db.session.commit()
    return jsonify(drive_dict(db.session.get(SupplyDrive, pledge.drive_id)))


def hazard_dict(row):
    return {'id': row.id, 'name': db.session.get(User, row.user_id).display_name,
        'neighborhood_id': row.neighborhood_id, 'category': row.category, 'location': row.location,
        'description': row.description, 'status': row.status, 'created_at': row.created_at.isoformat() + 'Z'}


@preparedness_bp.route('/hazards', methods=['GET', 'POST'])
@requires_auth
def hazards():
    if request.method == 'GET':
        query = service.scoped(HazardReport.query, HazardReport, current_user)
        return jsonify({'hazards': [hazard_dict(h) for h in query.order_by(HazardReport.created_at.desc()).all()]})
    data = body()
    if data.get('category') not in ('tree', 'route', 'hydrant', 'other'):
        raise BadRequest('Choose a hazard category.')
    report = HazardReport(user_id=current_user.id, neighborhood_id=service.neighborhood(data, True),
        category=data['category'], location=service.string(data, 'location', 300, True),
        description=service.string(data, 'description', 2000, True))
    db.session.add(report)
    db.session.commit()
    return jsonify(hazard_dict(report)), 201


@preparedness_bp.patch('/hazards/<int:report_id>')
@requires_min_role('coordinator')
def hazard_update(report_id):
    report = db.get_or_404(HazardReport, report_id)
    service.manage_neighborhood(current_user, report.neighborhood_id)
    status = body().get('status')
    if status not in ('open', 'reviewing', 'resolved'):
        raise BadRequest('Choose open, reviewing, or resolved.')
    report.status = status
    db.session.commit()
    return jsonify(hazard_dict(report))


@preparedness_bp.get('/preparedness/weekly')
def weekly():
    from app.services.risk_service import get_risk_assessment, RiskDataUnavailable
    today = datetime.now(ZoneInfo('America/Los_Angeles')).date()
    week = today - timedelta(days=today.weekday())
    risk = None
    try:
        risk = get_risk_assessment()
    except RiskDataUnavailable:
        pass
    threat = 'general'
    if risk:
        highest = max(('fire', 'flood', 'heat'), key=lambda k: risk.get(k + '_score', 0))
        if risk.get(highest + '_score', 0) >= 5:
            threat = highest
    tips = WeeklyTip.query.filter(WeeklyTip.week_start <= week, WeeklyTip.week_start >= week - timedelta(days=6),
        WeeklyTip.threat.in_(('general', threat))).order_by(WeeklyTip.id.desc()).all()
    # Weekly rotation links to existing preparedness content; no invented live alerts.
    rotating = [
        ('Review your kit', 'Check the kit checklist and replace expired supplies.'),
        ('Review your household plan', 'Confirm your meeting point and review neighborhood evacuation information.'),
        ('Connect with your neighbors', 'Check upcoming training events and available volunteer shifts.'),
        ('Review your contacts', 'Update your printed household emergency contacts.'),
    ]
    title, text = rotating[week.toordinal() // 7 % len(rotating)]
    if threat != 'general':
        title = {'fire': 'Wildfire preparedness this week', 'flood': 'Flood preparedness this week', 'heat': 'Heat preparedness this week'}[threat]
        text = 'Review the ' + {'fire': 'wildfire', 'flood': 'flood', 'heat': 'extreme heat'}[threat] + ' preparedness resources and local official alerts. Review your household plan and neighborhood resources.'
    # Existing event forms store local wall-clock dates without a timezone.
    now = datetime.now(ZoneInfo('America/Los_Angeles')).replace(tzinfo=None)
    events = Event.query.filter(Event.date >= now, Event.date < now + timedelta(days=7)).order_by(Event.date).all()
    return jsonify({'week_start': week.isoformat(), 'threat': threat,
        'risk_available': risk is not None, 'risk_is_stale': risk.get('is_stale', False) if risk else None,
        'risk_updated_at': risk.get('updated_at') if risk else None,
        'tips': [{'title': t.title, 'body': t.body, 'threat': t.threat} for t in tips] or [{'title': title, 'body': text, 'threat': threat}],
        'events': [e.to_dict() for e in events]})


@preparedness_bp.post('/preparedness/weekly')
@requires_min_role('staff')
def publish_tip():
    data = body()
    if data.get('threat') not in ('general', 'fire', 'flood', 'heat'):
        raise BadRequest('Choose general, fire, flood, or heat.')
    try:
        from datetime import date
        week = date.fromisoformat(data.get('week_start', ''))
        if week.weekday() != 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise BadRequest('week_start must be the Monday date in YYYY-MM-DD format.')
    tip = WeeklyTip(title=service.string(data, 'title', 200, True),
        body=service.string(data, 'body', 3000, True), threat=data['threat'], week_start=week)
    db.session.add(tip)
    db.session.commit()
    return jsonify({'id': tip.id}), 201
