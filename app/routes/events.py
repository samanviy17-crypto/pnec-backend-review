# app/routes/events.py
# Responsibility: Events API endpoints — list, calendar view, create.

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_login import current_user

from app.services import events_service
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role

events_bp = Blueprint('events', __name__)


@events_bp.route('/events', methods=['GET'])
def get_events():
    """Return upcoming events, sorted by date ascending."""
    events = events_service.get_upcoming_events(limit=50)
    return jsonify({'events': events}), 200


@events_bp.route('/events/calendar', methods=['GET'])
def get_calendar_events():
    """Return events for a specific month. Params: ?month=&year="""
    try:
        year  = int(request.args.get('year',  datetime.utcnow().year))
        month = int(request.args.get('month', datetime.utcnow().month))
    except (ValueError, TypeError):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'year and month must be integers'})

    events = events_service.get_events_for_month(year, month)
    return jsonify({'events': events, 'year': year, 'month': month}), 200


@events_bp.route('/events', methods=['POST'])
@requires_role('coordinator', 'staff', 'admin')
def create_event():
    """Create a new PNEC event. Coordinator+ only."""
    data = request.get_json(silent=True) or {}

    result, err = events_service.create_event(
        title=data.get('title', ''),
        description=data.get('description', ''),
        date_str=data.get('date', ''),
        location=data.get('location', ''),
        image_url=data.get('image_url'),
        created_by=current_user.id,
    )
    if err:
        return error_response(err, 400)
    return jsonify({'message': 'Event created.', 'event': result}), 201


@events_bp.route('/events/<int:event_id>', methods=['PATCH'])
@requires_role('coordinator', 'staff', 'admin')
def update_event(event_id):
    """Update an existing event. Coordinator+ only."""
    from app.models.event import Event
    from app import db
    from datetime import datetime as dt

    event = Event.query.get(event_id)
    if not event:
        return error_response('NOT_FOUND', 404)

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        event.title = (data['title'] or '').strip() or event.title
    if 'description' in data:
        event.description = data['description']
    if 'location' in data:
        event.location = data['location']
    if 'image_url' in data:
        event.image_url = data['image_url']
    if 'date' in data:
        try:
            event.date = dt.fromisoformat(data['date'].replace('Z', '+00:00')).replace(tzinfo=None)
        except (ValueError, AttributeError):
            return error_response('VALIDATION_FAILED', 400, {'detail': 'date must be ISO 8601'})

    db.session.commit()
    return jsonify({'message': 'Event updated.', 'event': event.to_dict()}), 200


@events_bp.route('/events/<int:event_id>', methods=['DELETE'])
@requires_role('coordinator', 'staff', 'admin')
def delete_event(event_id):
    """Delete an event. Coordinator+ only."""
    from app.models.event import Event
    from app import db

    event = Event.query.get(event_id)
    if not event:
        return error_response('NOT_FOUND', 404)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Event deleted.'}), 200
