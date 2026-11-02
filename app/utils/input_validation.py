"""Bounded JSON objects, text and queries; validation errors are controlled 400s."""
from flask import request
from werkzeug.exceptions import BadRequest


def json_object(allowed):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise BadRequest('Submit a JSON object containing only supported fields.')
    return data


def text(value, key, maximum, required=False, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise BadRequest(f'{key} must be text, at most {maximum} characters' + (' and nonempty.' if required else '.'))
    return value.strip()


def query_integer(key, default, low, high):
    raw = request.args.get(key, str(default))
    if len(raw) > 10 or not raw.isascii() or not raw.isdecimal() or not low <= int(raw) <= high:
        raise BadRequest(f'{key} must be an integer between {low} and {high}.')
    return int(raw)
