# app/utils/security.py
# PNEC site security hardening — utilities and middleware.
#
# Threat model: PNEC's site is a community emergency-prep org.
# Real risks:
#   • Defacement attacks (admin account takeover → spray-paint the site)
#   • Credential stuffing (rate limits + lockout below)
#   • Site outages during actual emergencies (the moment it matters most)
#   • Common XSS / clickjacking against admin tools
#   • Resource abuse (push subscribe SSRF — already patched)
#
# This module addresses A02 Security Misconfiguration (OWASP Top 10
# 2026, moved from #5 → #2): HTTP response headers that browsers
# enforce as defense-in-depth, plus account lockout state, audit
# event helpers, and constant-time comparisons.

import hmac
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import current_app, request, jsonify, g


# ─── Account lockout ───────────────────────────────────────────────────────
#
# Per-email tracking — rate limiting (in auth.py) blocks brute force on a
# single IP, but a distributed attack can hit one account from 1000 IPs at
# 5 attempts each. Lockout caps the per-email budget regardless of IP.
#
# Development retains the existing in-memory buckets. Production uses the
# process-shared, locked runtime store in shared_limits.py. Multi-host deployments
# require an approved distributed limiter instead of this single-host store.

_LOCKOUT_FAILED_THRESHOLD = 5            # failures within window before lock
_LOCKOUT_WINDOW_SEC       = 15 * 60       # rolling 15-minute window
_LOCKOUT_DURATION_SEC     = 15 * 60       # lock duration after threshold

_failed_attempts: dict[str, list[float]] = defaultdict(list)
_locked_until:    dict[str, float]       = {}


def _normalize_email(email: str) -> str:
    return (email or '').strip().lower()


def is_account_locked(email: str) -> tuple[bool, int]:
    """Return (locked, seconds_remaining)."""
    e = _normalize_email(email)
    if not e:
        return False, 0
    from app.utils import shared_limits
    if shared_limits.enabled():
        status = shared_limits.account_status(e)
        return status['locked'], status['unlock_in_sec']
    until = _locked_until.get(e, 0)
    now = time.time()
    if until > now:
        return True, int(until - now) + 1
    return False, 0


def record_login_failure(email: str) -> tuple[bool, int]:
    """Record a failed login. Returns (now_locked, attempts_remaining)."""
    e = _normalize_email(email)
    if not e:
        return False, _LOCKOUT_FAILED_THRESHOLD
    from app.utils import shared_limits
    if shared_limits.enabled():
        status = shared_limits.account_status(e, failure=True)
        return status['locked'], max(0, 5 - status['failed_in_window']) if not status['locked'] else 0
    now = time.time()
    bucket = [t for t in _failed_attempts.get(e, []) if now - t < _LOCKOUT_WINDOW_SEC]
    bucket.append(now)
    _failed_attempts[e] = bucket
    if len(bucket) >= _LOCKOUT_FAILED_THRESHOLD:
        _locked_until[e] = now + _LOCKOUT_DURATION_SEC
        # Reset the bucket so the lock is for exactly DURATION, not the
        # rolling-window leftover
        _failed_attempts[e] = []
        return True, 0
    return False, max(0, _LOCKOUT_FAILED_THRESHOLD - len(bucket))


def record_login_success(email: str) -> None:
    """Clear lockout state for an email after a successful login."""
    e = _normalize_email(email)
    from app.utils import shared_limits
    if shared_limits.enabled():
        shared_limits.account_status(e, clear=True)
        return
    _failed_attempts.pop(e, None)
    _locked_until.pop(e, None)


def lockout_status(email: str) -> dict:
    """Return current lockout state — used by the admin dashboard."""
    e = _normalize_email(email)
    locked, secs = is_account_locked(e)
    from app.utils import shared_limits
    bucket = _failed_attempts.get(e, [])
    count = shared_limits.account_status(e)['failed_in_window'] if shared_limits.enabled() else len(bucket)
    return {
        'email':            e,
        'locked':           locked,
        'unlock_in_sec':    secs,
        'failed_in_window': count,
        'window_sec':       _LOCKOUT_WINDOW_SEC,
        'threshold':        _LOCKOUT_FAILED_THRESHOLD,
    }


# ─── HTTP security headers ─────────────────────────────────────────────────
#
# Every API response carries these headers. The frontend is served by
# Jekyll/static hosting which adds its own headers; these protect API
# consumers (and the editor iframe) from common attacks.

# Default Content-Security-Policy. Permissive enough to keep the existing
# editor + chatbot working (inline-style + inline-script + WP-CDN images
# all in use), but strict enough to block obvious XSS injection vectors.
# Tighten over time — see pnec_admin_setup_guide_todo.md.
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://generativelanguage.googleapis.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://powaynec.com; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data: https://fonts.gstatic.com https://powaynec.com; "
    "connect-src 'self' https: wss:; "
    "frame-ancestors 'self' https://pnec-review.invalid http://localhost:* http://127.0.0.1:*; "
    "form-action 'self' https://www.paypal.com; "
    "base-uri 'self'; "
    "object-src 'none';"
)


def install_security_headers(app):
    """Wire after_request hook that adds security headers to every API response.

    Headers added:
      • X-Frame-Options: SAMEORIGIN — prevents clickjacking via iframe
      • X-Content-Type-Options: nosniff — stops MIME-type sniffing
      • Referrer-Policy: strict-origin-when-cross-origin — leaks less
        about admin URLs to third-party sites
      • Permissions-Policy: locks down browser features the API doesn't
        need (camera, mic, geolocation, etc.)
      • Content-Security-Policy: defense-in-depth XSS mitigation
      • Strict-Transport-Security: forces HTTPS for 1 year
      • X-Permitted-Cross-Domain-Policies: none — blocks Flash/PDF
        cross-domain access
      • Cross-Origin-Opener-Policy: same-origin — isolates browsing
        context (also enables future SharedArrayBuffer if needed)
    """
    csp = app.config.get('CSP_HEADER', _DEFAULT_CSP)

    @app.after_request
    def _add_security_headers(response):
        # Skip for non-API responses (Flask static file serving etc.)
        # Actually safer to add to ALL responses since the API doesn't
        # serve HTML pages.
        h = response.headers
        h['X-Frame-Options']                  = 'SAMEORIGIN'
        h['X-Content-Type-Options']           = 'nosniff'
        h['Referrer-Policy']                  = 'strict-origin-when-cross-origin'
        h['Permissions-Policy']               = (
            'accelerometer=(), camera=(), geolocation=(), gyroscope=(), '
            'magnetometer=(), microphone=(), payment=(), usb=()'
        )
        h['X-Permitted-Cross-Domain-Policies'] = 'none'
        h['Cross-Origin-Opener-Policy']       = 'same-origin'
        # CSP only on JSON/HTML responses — applying to images/binary
        # would be wasteful and harmless but adds bytes to every byte
        # served.
        ct = (h.get('Content-Type') or '').lower()
        if ct.startswith('application/json') or ct.startswith('text/html'):
            h['Content-Security-Policy'] = csp
        # HSTS only when serving over HTTPS — adding it to plain HTTP
        # responses is at best a no-op, at worst can lock dev servers
        # out if anything misroutes through HTTP.
        if request.is_secure:
            h['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response


# ─── Constant-time comparison ──────────────────────────────────────────────


def safe_compare(a: str, b: str) -> bool:
    """Constant-time string comparison — avoids timing leaks on token
    + bearer-token verification. Wraps hmac.compare_digest with the
    string conversion."""
    if a is None or b is None:
        return False
    return hmac.compare_digest(str(a).encode('utf-8'), str(b).encode('utf-8'))


# ─── Sensitive event audit logging ─────────────────────────────────────────
#
# Convenience wrappers for SecurityEvent (defined in models/security_event.py).
# Use these from any route that performs a sensitive action.

def log_event(kind: str, *,
              actor_id: int | None = None,
              actor_email: str | None = None,
              detail: str | None = None,
              ip: str | None = None,
              extra: dict | None = None,
              severity: str = 'info'):
    """Append a row to security_events. Best-effort — never raises."""
    try:
        from app import db
        from app.models.security_event import SecurityEvent
        ev = SecurityEvent(
            kind=(kind or 'unknown')[:40],
            actor_id=actor_id,
            actor_email=(actor_email or '')[:254] or None,
            detail=(detail or '')[:1000] or None,
            ip=(ip or _client_ip())[:64] or None,
            user_agent=(request.headers.get('User-Agent') or '')[:300] or None,
            severity=severity,
            extra_json=_serialize(extra),
        )
        db.session.add(ev)
        db.session.commit()
        return ev
    except Exception:
        try:
            current_app.logger.exception('log_event failed for kind=%s', kind)
        except Exception:
            pass
        return None


def _client_ip() -> str:
    return ((request.remote_addr or '')
            .split(',')[0].strip() or '_')


def _serialize(extra) -> str | None:
    if extra is None:
        return None
    try:
        import json
        return json.dumps(extra, default=str)[:2000]
    except Exception:
        return None


# ─── Suspicious-activity heuristics ────────────────────────────────────────
#
# Quick checks that admin routes can use to flag unusual access
# patterns. Not a replacement for a real WAF but catches the lazy stuff.

_SUSPICIOUS_UA_PATTERNS = (
    'sqlmap', 'nmap', 'nikto', 'masscan', 'dirbuster', 'gobuster',
    'wpscan', 'havij', 'curl', 'wget', 'python-requests', 'scrapy',
)


def is_suspicious_user_agent(ua: str | None) -> bool:
    """True if the user-agent matches a common automated-tool signature.

    This isn't a block — the admin UI surfaces it as a flag on the
    event row so an analyst can see "this login attempt came from a
    sqlmap-shaped client". Real analysts spoof their UA, so absence
    of a flag isn't safety. Presence is a strong signal.
    """
    if not ua:
        return True   # empty UA on a browser request is itself suspicious
    u = ua.lower()
    return any(p in u for p in _SUSPICIOUS_UA_PATTERNS)


def currently_locked_emails():
    from app.utils import shared_limits
    if shared_limits.enabled():
        return shared_limits.locked_emails()
    return [email for email, until in list(_locked_until.items()) if until > time.time()]
