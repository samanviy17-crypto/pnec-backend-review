# app/routes/push.py
import json
import re
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app import db
from app.models.push_subscription import PushSubscription
from app.utils.errors import error_response

push_bp = Blueprint('push', __name__)

# SSRF defense: only let admins push to endpoints owned by real push
# providers. Without this allowlist, an attacker could insert
# subscription rows pointing at internal IPs / arbitrary URLs and
# coerce the server to make outbound HTTP calls there on the next push.
_ALLOWED_PUSH_HOSTS = (
    'fcm.googleapis.com',           # Chrome / Android
    'updates.push.services.mozilla.com',  # Firefox
)
_ALLOWED_PUSH_HOST_SUFFIXES = (
    '.push.apple.com',              # Safari (e.g. push3.push.apple.com)
    '.notify.windows.com',          # Edge legacy
    '.googleapis.com',              # other GCM/FCM
)


def _is_allowed_push_endpoint(endpoint):
    if not endpoint or not isinstance(endpoint, str) or len(endpoint) > 1024:
        return False
    try:
        u = urlparse(endpoint)
    except Exception:
        return False
    if u.scheme != 'https' or not u.netloc:
        return False
    host = u.hostname or ''
    if host in _ALLOWED_PUSH_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in _ALLOWED_PUSH_HOST_SUFFIXES)


@push_bp.route('/push/vapid-public-key', methods=['GET'])
def get_vapid_public_key():
    key = current_app.config.get('VAPID_PUBLIC_KEY', '')
    return jsonify({'publicKey': key}), 200


@push_bp.route('/push/subscribe', methods=['POST'])
def subscribe():
    """Register a push subscription for the current user.

    SECURITY (added after audit):
      • Requires an authenticated session — anonymous subscribe was an
        unbounded spam vector for the PushSubscription table.
      • Endpoint URL must belong to a known push provider (FCM, Apple,
        Mozilla, Microsoft) — defense against SSRF where the server
        would make outbound HTTP calls to attacker-controlled hosts on
        the next admin "send push".
    """
    if not current_user.is_authenticated:
        return error_response('UNAUTHORIZED', 401, {'detail': 'Sign in to subscribe to push notifications.'})

    data = request.get_json(silent=True) or {}
    subscription = data.get('subscription', {}) or {}
    endpoint = (subscription.get('endpoint') or '').strip()
    keys = subscription.get('keys', {}) or {}
    p256dh = (keys.get('p256dh') or '').strip()
    auth = (keys.get('auth') or '').strip()

    if not all([endpoint, p256dh, auth]):
        return error_response('VALIDATION_FAILED', 400, {'detail': 'Invalid push subscription.'})

    if not _is_allowed_push_endpoint(endpoint):
        return error_response('VALIDATION_FAILED', 400,
                              {'detail': 'Endpoint host is not an allowed push provider.'})

    # Bound the key fields so the table can't be stuffed with garbage
    if len(p256dh) > 200 or len(auth) > 64:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'Subscription keys are oversized.'})

    user_id = current_user.id

    existing = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if existing:
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_id = user_id
    else:
        sub = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, user_id=user_id)
        db.session.add(sub)

    db.session.commit()
    return jsonify({'ok': True}), 200


@push_bp.route('/push/send', methods=['POST'])
def send_push():
    if not current_user.is_authenticated:
        return error_response('UNAUTHORIZED', 401)

    data = request.get_json(silent=True) or {}
    title = data.get('title', 'PNEC Alert')
    body = data.get('body', '')
    url = data.get('url', '/')

    subscriptions = PushSubscription.query.filter_by(user_id=current_user.id).all()
    if not subscriptions:
        return jsonify({'ok': True, 'sent': 0, 'detail': 'No subscriptions found.'}), 200

    sent = _send_push_notifications(subscriptions, title, body, url)
    return jsonify({'ok': True, 'sent': sent}), 200


def _send_push_notifications(subscriptions, title, body, url='/'):
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        current_app.logger.warning('pywebpush not installed — push notifications disabled.')
        return 0

    vapid_private = current_app.config.get('VAPID_PRIVATE_KEY', '')
    vapid_email = current_app.config.get('VAPID_EMAIL', 'contact@example.test')

    if not vapid_private:
        return 0

    payload = json.dumps({'title': title, 'body': body, 'url': url, 'icon': '/assets/images/pnec-icon-192.png'})
    sent = 0
    to_remove = []

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
                },
                data=payload,
                vapid_private_key=vapid_private,
                vapid_claims={'sub': f'mailto:{vapid_email}'},
            )
            sub.last_used = datetime.utcnow()
            sent += 1
        except Exception as ex:
            if '410' in str(ex) or '404' in str(ex):
                to_remove.append(sub)

    for sub in to_remove:
        db.session.delete(sub)
    if to_remove or sent:
        db.session.commit()

    return sent
