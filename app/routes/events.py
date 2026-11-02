# app/routes/events.py
# Responsibility: Events API endpoints — list, calendar view, create.

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_login import current_user

from app.services import events_service
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role
from app.utils.input_validation import json_object, query_integer
from werkzeug.exceptions import HTTPException

events_bp = Blueprint('events', __name__)


@events_bp.errorhandler(HTTPException)
def controlled_error(error):
    return jsonify({'message': error.description}), error.code


@events_bp.route('/events', methods=['GET'])
def get_events():
    """Return upcoming events, sorted by date ascending."""
    events = events_service.get_upcoming_events(limit=50)
    return jsonify({'events': events}), 200


@events_bp.route('/events/calendar', methods=['GET'])
def get_calendar_events():
    """Return events for a specific month. Params: ?month=&year="""
    year = query_integer('year', datetime.utcnow().year, 1900, 9998)
    month = query_integer('month', datetime.utcnow().month, 1, 12)

    events = events_service.get_events_for_month(year, month, request.args.get('timezone', 'America/Los_Angeles'))
    return jsonify({'events': events, 'year': year, 'month': month}), 200


@events_bp.route('/events', methods=['POST'])
@requires_role('coordinator', 'staff', 'admin')
def create_event():
    """Create a new PNEC event. Coordinator+ only."""
    data = json_object(events_service.FIELDS)

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

    event = Event.query.get(event_id)
    if not event:
        return error_response('NOT_FOUND', 404)

    data = json_object(events_service.FIELDS)
    values = events_service.validated_fields(data, partial=True)
    from app.utils.event_time import utc_value
    utc_value(values.get('date', event.date))
    for field, value in values.items():
        setattr(event, field, value)

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
    from app.models.media import MediaPost
    if MediaPost.query.filter_by(event_id=event.id).first():
        return error_response('VALIDATION_FAILED', 409, {'detail': 'Event has gallery entries. Retain it or explicitly unlink/reassign entries before deletion.'})
    from sqlalchemy.exc import IntegrityError
    db.session.delete(event)
    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent gallery insertion also restricts deletion atomically.
        db.session.rollback()
        return error_response('VALIDATION_FAILED', 409, {'detail': 'Event is referenced by gallery data; retain or explicitly unlink it.'})
    return jsonify({'message': 'Event deleted.'}), 200
