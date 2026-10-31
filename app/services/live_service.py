# app/services/live_service.py
# Responsibility: Aggregate "right now" Poway conditions for the PNEC
# chatbot — weather, air quality, NWS active alerts, fire-weather
# composite, and sun position. The chatbot injects this into its
# system prompt on every send so the bot never says "I don't have
# current data."
#
# Upstream sources (all free, all no-key):
#   - Open-Meteo forecast        (already wrapped by risk_service)
#   - Open-Meteo air quality     (already wrapped by risk_service)
#   - api.weather.gov alerts     (NWS, point-based, no key)
#   - api.sunrise-sunset.org     (sunrise/sunset, no key)
#
# Caching: 30-minute server-side cache per the env override
# LIVE_CACHE_SECONDS so a busy chatbot day still results in only
# 48 upstream fetches/day at most.

import time
from datetime import datetime, timezone

import requests
from flask import current_app

from app.services import risk_service

_live_cache = {'data': None, 'expires_at': 0}


def get_live_conditions():
    """Aggregate current Poway conditions for chatbot consumption."""
    now = time.time()
    if _live_cache['data'] and _live_cache['expires_at'] > now:
        return _live_cache['data']

    # Reuse the existing risk_service for weather/AQI — it already
    # caches Open-Meteo for 30 min and computes fire/flood/heat scores.
    risk = {}
    try:
        risk = risk_service.get_risk_assessment(neighborhood_id=None) or {}
    except Exception:
        try:
            current_app.logger.exception('live.risk_assessment failed')
        except Exception:
            pass

    weather = _extract_weather(risk)
    air_quality = _extract_aqi(risk)
    fire_weather = _extract_fire_weather(risk)

    alerts = _fetch_nws_alerts()
    sun = _fetch_sun()

    recommendation = _make_recommendation(weather, air_quality, fire_weather, alerts)

    payload = {
        'fetched_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        'weather': weather,
        'air_quality': air_quality,
        'fire_weather': fire_weather,
        'alerts': alerts,
        'sun': sun,
        'recommendation': recommendation,
    }

    _live_cache['data'] = payload
    _live_cache['expires_at'] = now + current_app.config.get('LIVE_CACHE_SECONDS', 1800)
    return payload


def _extract_weather(risk):
    """Pull the flat conditions dict out of the risk_service shape.

    risk_service returns:
      { 'conditions': {temp_f, humidity, wind_mph, precip_in,
                       rain_7d_in, heat_index_f, us_aqi, pm2_5, pm10},
        'fire_score', 'fire_level', ... }
    """
    cur = (risk or {}).get('conditions') or {}
    return {
        'temp_f':     cur.get('temp_f'),
        'humidity':   cur.get('humidity'),
        'wind_mph':   cur.get('wind_mph'),
        'precip_in':  cur.get('precip_in') if cur.get('precip_in') is not None else cur.get('precip_1hr_in'),
        'rain_7d_in': cur.get('rain_7d_in'),
        'heat_index_f': cur.get('heat_index_f'),
    }


def _extract_aqi(risk):
    cur = (risk or {}).get('conditions') or {}
    return {
        'us_aqi': cur.get('us_aqi'),
        'pm2_5':  cur.get('pm2_5'),
        'pm10':   cur.get('pm10'),
    }


def _extract_fire_weather(risk):
    """Build a fire-weather composite from the risk_service score + drivers.

    risk_service exposes:
      fire_score (0-10 int), fire_level ('LOW'/'MODERATE'/'HIGH'/'CRITICAL')
    We synthesize a 'drivers' list by inspecting the same conditions
    that compute_fire_risk uses (temp, humidity, wind, dryness).
    """
    score = (risk or {}).get('fire_score')
    if score is None:
        return {'score': 0, 'label': 'Low', 'drivers': []}

    label = (risk or {}).get('fire_level') or (
        'Critical' if score >= 8 else 'High' if score >= 6 else
        'Moderate' if score >= 4 else 'Low'
    )

    cur = (risk or {}).get('conditions') or {}
    drivers = []
    if (cur.get('temp_f') or 0) >= 95:
        drivers.append('triple-digit heat')
    elif (cur.get('temp_f') or 0) >= 85:
        drivers.append('warm air')
    if (cur.get('humidity') or 100) <= 20:
        drivers.append('humidity ≤20% (dangerous)')
    elif (cur.get('humidity') or 100) <= 30:
        drivers.append('low humidity')
    if (cur.get('wind_mph') or 0) >= 25:
        drivers.append('high wind')
    elif (cur.get('wind_mph') or 0) >= 15:
        drivers.append('breezy')
    if (cur.get('rain_7d_in') or 0) <= 0.1:
        drivers.append('no rain past week (dry fuels)')

    return {'score': int(score), 'label': str(label).title(), 'drivers': drivers}


def _fetch_nws_alerts():
    """Active NWS alerts for the Poway point (San Diego County)."""
    lat = current_app.config.get('POWAY_LAT', 32.9628)
    lon = current_app.config.get('POWAY_LON', -117.0359)
    # NWS requires a User-Agent identifying the app. Be courteous — they
    # rate-limit anonymous traffic.
    headers = {
        'User-Agent': f"PNEC-HelperBot/3.8 ({current_app.config.get('PUBLIC_CONTACT_EMAIL') or 'contact-unconfigured'})",
        'Accept': 'application/geo+json',
    }
    try:
        url = f'https://api.weather.gov/alerts/active?point={lat},{lon}'
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        features = (resp.json() or {}).get('features') or []
        out = []
        for feat in features[:8]:
            props = feat.get('properties') or {}
            out.append({
                'event':       props.get('event'),
                'severity':    props.get('severity'),
                'urgency':     props.get('urgency'),
                'headline':    props.get('headline'),
                'description': (props.get('description') or '')[:600],
                'starts':      props.get('onset') or props.get('effective'),
                'ends':        props.get('ends') or props.get('expires'),
                'sender':      props.get('senderName'),
            })
        return out
    except Exception:
        try:
            current_app.logger.exception('live.nws_alerts failed')
        except Exception:
            pass
        return []


def _fetch_sun():
    """Today's sunrise/sunset for Poway (in local time strings)."""
    lat = current_app.config.get('POWAY_LAT', 32.9628)
    lon = current_app.config.get('POWAY_LON', -117.0359)
    try:
        url = 'https://api.sunrise-sunset.org/json'
        resp = requests.get(url, params={
            'lat': lat, 'lng': lon, 'formatted': 0
        }, timeout=6)
        resp.raise_for_status()
        results = (resp.json() or {}).get('results') or {}
        # Convert UTC ISO timestamps to local PT for display.
        from zoneinfo import ZoneInfo
        pt = ZoneInfo('America/Los_Angeles')

        def fmt(iso):
            if not iso:
                return None
            try:
                dt = datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(pt)
                return dt.strftime('%I:%M %p PT').lstrip('0')
            except Exception:
                return None

        return {
            'sunrise': fmt(results.get('sunrise')),
            'sunset':  fmt(results.get('sunset')),
            'civil_twilight_begin': fmt(results.get('civil_twilight_begin')),
            'civil_twilight_end':   fmt(results.get('civil_twilight_end')),
        }
    except Exception:
        return {}


def _make_recommendation(weather, aqi, fire, alerts):
    """One-line plain-English recommendation the chatbot can quote."""
    pieces = []

    if alerts:
        # Surface the most-severe NWS alert first.
        sev_rank = {'Extreme': 4, 'Severe': 3, 'Moderate': 2, 'Minor': 1, 'Unknown': 0}
        worst = max(alerts, key=lambda a: sev_rank.get((a.get('severity') or 'Unknown'), 0))
        pieces.append(f"NWS {worst.get('severity', '')} — {worst.get('event', 'alert')}.")

    score = (fire or {}).get('score')
    if isinstance(score, (int, float)) and score >= 6:
        pieces.append('Fire-weather is HIGH — postpone outdoor sparks/welding/mowing dry brush.')
    elif isinstance(score, (int, float)) and score >= 4:
        pieces.append('Fire-weather is elevated — be cautious with anything that throws sparks.')

    aqi_val = (aqi or {}).get('us_aqi')
    if isinstance(aqi_val, (int, float)):
        if aqi_val > 150:
            pieces.append('AQI is unhealthy — stay indoors with windows closed.')
        elif aqi_val > 100:
            pieces.append('AQI is unhealthy for sensitive groups — limit exertion outdoors if you have asthma/heart conditions.')

    temp = (weather or {}).get('temp_f')
    if isinstance(temp, (int, float)) and temp >= 100:
        pieces.append(f'It is {int(temp)}°F — heat-illness risk. Hydrate, check on neighbors over 65.')

    if not pieces:
        pieces.append('Conditions are normal for Poway right now.')
    return ' '.join(pieces)
