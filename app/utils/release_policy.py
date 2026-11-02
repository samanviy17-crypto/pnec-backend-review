"""Fail-closed, server-controlled policy without production schema changes."""
import json
import os
from flask import current_app


def configure_release_policy(app):
    raw = os.environ.get('COORDINATOR_ASSIGNMENTS')
    assignments = app.config['COORDINATOR_ASSIGNMENTS']
    if raw is not None:
        try:
            assignments = json.loads(raw)
        except ValueError:
            raise RuntimeError('COORDINATOR_ASSIGNMENTS must be a JSON object.') from None
    if (not isinstance(assignments, dict) or any(
            not isinstance(k, str) or not k.isascii() or not k.isdecimal() or int(k) < 1
            or type(v) is not int or v < 1 for k, v in assignments.items())):
        raise RuntimeError('COORDINATOR_ASSIGNMENTS must map account ID strings to positive neighborhood IDs.')
    app.config['COORDINATOR_ASSIGNMENTS'] = dict(assignments)
    zone = os.environ.get('EVENT_STORAGE_TIMEZONE', app.config['EVENT_STORAGE_TIMEZONE'])
    if zone not in (None, 'UTC', 'America/Los_Angeles'):
        raise RuntimeError('Review EVENT_STORAGE_TIMEZONE: UTC or America/Los_Angeles only.')
    app.config['EVENT_STORAGE_TIMEZONE'] = zone


def coordinator_neighborhood(user):
    # Missing/unreviewed assignments grant no access; residence is never fallback.
    return current_app.config['COORDINATOR_ASSIGNMENTS'].get(str(user.id))
