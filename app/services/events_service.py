# app/services/events_service.py
# Responsibility: Events business logic — create, list, and calendar filtering.

from datetime import datetime
from app import db
from app.models.event import Event


def get_upcoming_events(limit=20):
    """
    Purpose: Return all future events ordered by date ascending.
    @param {int} limit - Maximum number of events to return
    @returns {list} List of event dicts
    Algorithm:
    1. Query events where date >= now
    2. Order by date ascending
    3. Apply limit
    4. Return as list of dicts
    """
    now = datetime.utcnow()
    events = (Event.query
              .filter(Event.date >= now)
              .order_by(Event.date.asc())
              .limit(limit)
              .all())
    return [e.to_dict() for e in events]


def get_events_for_month(year, month):
    """
    Purpose: Return all events occurring within a specific calendar month.
    @param {int} year  - Four-digit year
    @param {int} month - Month number (1–12)
    @returns {list} List of event dicts for the given month
    Algorithm:
    1. Compute month start and end datetimes
    2. Query events within the range
    3. Return list of dicts
    """
    from calendar import monthrange
    start = datetime(year, month, 1)
    _, last_day = monthrange(year, month)
    end = datetime(year, month, last_day, 23, 59, 59)

    events = (Event.query
              .filter(Event.date >= start, Event.date <= end)
              .order_by(Event.date.asc())
              .all())
    return [e.to_dict() for e in events]


def create_event(title, description, date_str, location, image_url=None, created_by=None):
    """
    Purpose: Validate and create a new PNEC event.
    @param {str}      title       - Event title (required)
    @param {str}      description - Event description
    @param {str}      date_str    - ISO format date string
    @param {str}      location    - Venue or address
    @param {str|None} image_url   - Optional image URL
    @param {int|None} created_by  - User id of creator
    @returns {tuple} (event dict, None) on success, (None, error_key) on failure
    Algorithm:
    1. Validate required fields
    2. Parse date string
    3. Create Event record
    4. Persist and return dict
    """
    if not title or not date_str:
        return None, 'VALIDATION_FAILED'

    try:
        event_date = datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None, 'VALIDATION_FAILED'

    event = Event(
        title=title.strip(),
        description=(description or '').strip(),
        date=event_date,
        location=(location or '').strip(),
        image_url=image_url,
        created_by=created_by,
    )
    db.session.add(event)
    db.session.commit()
    return event.to_dict(), None
