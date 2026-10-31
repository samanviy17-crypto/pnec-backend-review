"""Single-host, multi-process limiter with a locked, versioned runtime file.

All Gunicorn workers must share this local filesystem path. This is not a
multi-host limiter. State failures fail closed; no application schema changes.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from flask import current_app
from werkzeug.exceptions import ServiceUnavailable


def enabled():
    return current_app.config['RATE_LIMIT_STORAGE'] == 'file'


def _key(kind, identity):
    return kind + ':' + hashlib.sha256(identity.encode()).hexdigest()


@contextmanager
def state():
    path = Path(current_app.config['SECURITY_STATE_PATH'])
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(str(path) + '.lock', flags, 0o600), 'r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))) as source:
                    if os.fstat(source.fileno()).st_size > 4 * 1024 * 1024:
                        raise ValueError('Limiter state capacity exceeded')
                    payload = json.load(source)
                if payload.get('version') != 1 or not isinstance(payload.get('entries'), dict):
                    raise ValueError('Unsupported limiter state')
            else:
                payload = {'version': 1, 'entries': {}}
            now = time.time()
            entries = {k: v for k, v in payload['entries'].items() if v['expires'] > now}
            if len(entries) > 10000:
                raise ValueError('Limiter state capacity exceeded')
            yield entries
            fd, temporary = tempfile.mkstemp(prefix='.security-limits-', dir=path.parent)
            with os.fdopen(fd, 'w') as target:
                json.dump({'version': 1, 'entries': entries}, target)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
            temporary = None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Do not log identities, credentials, configuration values or paths.
        raise ServiceUnavailable('Authentication protection unavailable. Try again later.') from None
    finally:
        if temporary:
            os.unlink(temporary)


def rate_limited(kind, identity, limit, window):
    now = time.time()
    with state() as entries:
        key = _key('rate:' + kind, identity)
        bucket = [t for t in entries.get(key, {}).get('attempts', []) if now - t < window]
        limited = len(bucket) >= limit
        if not limited:
            bucket.append(now)
        entries[key] = {'attempts': bucket, 'expires': now + window}
        return limited


def account_status(email, failure=False, clear=False):
    now = time.time()
    with state() as entries:
        key = _key('account', email)
        record = entries.get(key, {})
        if clear:
            entries.pop(key, None)
            return {'locked': False, 'unlock_in_sec': 0, 'failed_in_window': 0}
        until = record.get('until', 0)
        bucket = [t for t in record.get('attempts', []) if now - t < 900]
        if failure and until <= now:
            bucket.append(now)
            if len(bucket) >= 5:
                until, bucket = now + 900, []
            entries[key] = {'email': email, 'until': until, 'attempts': bucket, 'expires': now + 900}
        return {'locked': until > now, 'unlock_in_sec': max(0, int(until - now) + 1), 'failed_in_window': len(bucket)}


def locked_emails():
    with state() as entries:
        return [v['email'] for k, v in entries.items() if k.startswith('account:') and v.get('until', 0) > time.time()]
