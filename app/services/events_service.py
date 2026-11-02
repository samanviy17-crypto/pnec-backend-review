"""Event validation and UTC comparisons, with explicit legacy storage semantics."""
from datetime import datetime, timezone
from app import db
from app.models.event import Event
from app.utils.event_time import parse_event_date, utc_value
from app.utils.input_validation import text

FIELDS = {'title', 'description', 'date', 'location', 'image_url'}


def validated_fields(data, partial=False):
    from werkzeug.exceptions import BadRequest
    from urllib.parse import urlsplit
    if not isinstance(data, dict) or set(data) - FIELDS or not data:
        raise BadRequest('Submit only supported event fields.')
    if not partial and not {'title', 'date'}.issubset(data):
        raise BadRequest('title and date are required.')
    values = {}
    for key, maximum in [('title', 200), ('description', 10000), ('location', 200), ('image_url', 500)]:
        if key in data:
            values[key] = text(data[key], key, maximum, required=key == 'title', nullable=key != 'title')
    if values.get('image_url'):
        try:
            parsed = urlsplit(values['image_url'])
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
        except ValueError:
            raise BadRequest('image_url must be a public HTTPS URL.') from None
    if 'date' in data:
        values['date'] = parse_event_date(data['date'])
    return values


def events_between(start, end=None, limit=None):
    # Convert each stored value before comparison: UTC bounds also work across
    # DST and month boundaries in an explicitly reviewed legacy local database.
    rows = [(utc_value(e.date), e) for e in Event.query.all()]
    rows = sorted((pair for pair in rows if pair[0] >= start and (end is None or pair[0] < end)), key=lambda pair: pair[0])
    if limit is not None:
        rows = rows[:limit]
    return [e.to_dict() for _, e in rows]


def get_upcoming_events(limit=20):
    return events_between(datetime.now(timezone.utc), limit=limit)


def get_events_for_month(year, month, calendar_timezone='America/Los_Angeles'):
    # Calendar boundaries follow the viewer, independently of storage convention.
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    from werkzeug.exceptions import BadRequest
    if not isinstance(calendar_timezone, str) or len(calendar_timezone) > 100:
        raise BadRequest('timezone must be a valid IANA timezone.')
    try:
        zone = ZoneInfo(calendar_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise BadRequest('timezone must be a valid IANA timezone.') from None
    start = datetime(year, month, 1, tzinfo=zone).astimezone(timezone.utc)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=zone).astimezone(timezone.utc)
    return events_between(start, end)


def create_event(title, description, date_str, location, image_url=None, created_by=None):
    values = validated_fields({'title': title, 'description': description, 'date': date_str,
                               'location': location, 'image_url': image_url})
    event = Event(**values, created_by=created_by)
    db.session.add(event)
    db.session.commit()
    return event.to_dict(), None
