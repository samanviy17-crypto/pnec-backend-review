"""UTC API contract with explicit, non-mutating legacy storage interpretation."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import current_app
from werkzeug.exceptions import BadRequest, ServiceUnavailable


def storage_zone():
    name = current_app.config.get('EVENT_STORAGE_TIMEZONE')
    if name not in ('UTC', 'America/Los_Angeles'):
        raise ServiceUnavailable('Event timestamp interpretation requires owner review (EVENT_STORAGE_TIMEZONE).')
    return ZoneInfo(name)


def utc_value(stored):
    if stored.tzinfo is not None:
        return stored.astimezone(timezone.utc)
    zone = storage_zone()
    candidates = set()
    for fold in (0, 1):
        candidate = stored.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(zone).replace(tzinfo=None) == stored:
            candidates.add(candidate)
    if len(candidates) != 1:
        raise ServiceUnavailable('Ambiguous or nonexistent legacy event time requires owner review; no values were changed.')
    return candidates.pop()


def parse_event_date(value):
    if not isinstance(value, str) or len(value) > 40:
        raise BadRequest('date must be an ISO 8601 timestamp with a timezone.')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if instant.tzinfo is None or not 1900 <= instant.year <= 9998:
            raise ValueError()
        instant = instant.astimezone(timezone.utc)
        stored = instant.astimezone(storage_zone()).replace(tzinfo=None)
        # Wall-clock storage cannot represent two instants in a DST fold.
        if utc_value(stored) != instant:
            raise ValueError()
        return stored
    except (ValueError, OverflowError):
        raise BadRequest('date must be a valid, unambiguous ISO timestamp with a timezone (1900–9998).') from None


def serialize_event_date(stored):
    return utc_value(stored).isoformat().replace('+00:00', 'Z')
