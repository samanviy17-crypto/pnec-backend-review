"""Shared checklist, assessment and scoped community operations helpers."""
from datetime import datetime, timezone
from app import db
from sqlalchemy.exc import IntegrityError
from app.models.operations import HouseholdPreparedness
from app.models.neighborhood import Neighborhood
from werkzeug.exceptions import BadRequest, Forbidden

KIT_IDS = ('water', 'food', 'manual_can', 'water_tabs', 'first_aid', 'meds_7day',
           'otc_meds', 'first_aid_manual', 'flashlight', 'batteries', 'radio',
           'power_bank', 'blankets', 'dust_masks', 'gloves', 'rain_gear', 'docs',
           'cash', 'phone_list', 'whistle', 'evacuation', 'meeting')
QUIZ = [
    ('kit', 'Do you have a ready emergency kit?', 'Review and complete your emergency kit checklist.'),
    ('water', 'Have you stored water for your household?', 'Review the water section of your kit.'),
    ('food', 'Do you have food for your household?', 'Review the food section of your kit.'),
    ('medications', 'Are essential medications ready?', 'Review the first aid and medication section.'),
    ('route', 'Do you know your evacuation route?', 'Find your neighborhood and review its evacuation information.'),
    ('meeting', 'Have you chosen a household meeting point?', 'Save a household meeting point below.'),
    ('contacts', 'Do you have a printed emergency contact list?', 'Add a printed contact list to your kit.'),
    ('alerts', 'Do you know how to receive local emergency alerts?', 'Review the preparedness resources and local alert links.'),
    ('pets', 'Have you planned for pets or household access needs?', 'Include your household access needs and pets in your plan.'),
    ('practice', 'Have you practiced your household plan?', 'Arrange a household practice and review your plan together.'),
]


def record_for(user):
    row = db.session.get(HouseholdPreparedness, user.id)
    if row is None:
        row = HouseholdPreparedness(user_id=user.id)
        db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError:
            # Another request created the account record first.
            db.session.rollback()
            row = db.session.get(HouseholdPreparedness, user.id)
            if row is None:
                raise
    return row


def evaluate_preparedness(answers, questions, recommendation_limit=3):
    """Score validated answers against question records in a single bounded pass.

    Questions determine the denominator and recommendation order. Unknown answer
    keys never increase the score; absent answers count as not ready. The API
    still requires a complete boolean answer set before saving it.
    AI-assisted implementation (OpenAI Codex); personal Create authorship and
    eligibility must be established by the student, not inferred from this code.
    """
    ready = 0
    recommendations = []
    for key, _, tip in questions:
        if answers.get(key) is True:
            ready += 1
        elif len(recommendations) < recommendation_limit:
            recommendations.append(tip)
    score = round(ready / len(questions) * 100) if questions else 0
    return {'score': score, 'recommendations': recommendations}


def assessment(answers):
    """Keep the existing route/household interface for the ten-question quiz."""
    return evaluate_preparedness(answers, QUIZ)


def household_dict(row):
    items = row.items or {}
    return {'items': items, 'household_size': row.household_size or 1,
            'meeting_point': row.meeting_point or '', 'evacuation_plan': row.evacuation_plan or '',
            'quiz_answers': row.quiz_answers or {},
            'assessment': assessment(row.quiz_answers) if row.quiz_answers else None,
            'progress': round(sum(bool(items.get(k)) for k in KIT_IDS) / len(KIT_IDS) * 100)}


def string(data, key, maximum, required=False):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        raise BadRequest(f'{key} must be text, {"required, " if required else ""}at most {maximum} characters.')
    return value.strip()


def integer(data, key, low=1, high=1000000):
    value = data.get(key)
    if type(value) is not int or not low <= value <= high:
        raise BadRequest(f'{key} must be an integer between {low} and {high}.')
    return value


def neighborhood(data, required=False):
    value = data.get('neighborhood_id')
    if value is None and not required:
        return None
    if type(value) is not int or not Neighborhood.query.get(value):
        raise BadRequest('Choose an existing neighborhood.')
    return value


def scoped(query, model, user):
    if user.role in ('staff', 'admin'):
        return query
    if user.role == 'coordinator':
        if user.neighborhood_id is None:
            return query.filter(False)
        return query.filter(model.neighborhood_id == user.neighborhood_id)
    return query.filter(model.user_id == user.id)


def manage_neighborhood(user, neighborhood_id):
    if user.role not in ('coordinator', 'staff', 'admin'):
        raise Forbidden('Coordinator access required.')
    if user.role == 'coordinator' and (user.neighborhood_id is None or neighborhood_id != user.neighborhood_id):
        raise Forbidden('You can manage only your assigned neighborhood.')


def future_date(data):
    value = string(data, 'starts_at', 40, True)
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError()
        date = date.astimezone(timezone.utc).replace(tzinfo=None)
        if date <= datetime.utcnow():
            raise ValueError()
        return date
    except ValueError:
        raise BadRequest('starts_at must be a future ISO date with a timezone.')
