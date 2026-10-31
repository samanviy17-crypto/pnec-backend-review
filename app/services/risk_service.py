# app/services/risk_service.py
# Responsibility: Neighborhood-aware risk assessment and anomaly detection for
# wildfire, flood, and extreme heat in Poway.

from datetime import datetime, timedelta, timezone
import time

import requests
from flask import current_app

from app.models.neighborhood import Neighborhood

_risk_cache = {}


class RiskDataUnavailable(RuntimeError):
    """Raised when live risk data cannot be assembled from upstream sources."""

ZONE_FIRE_BONUS = {
    'A': 2,
    'B': 1,
    'C': 0,
    'D': -1,
}

ZONE_FLOOD_BONUS = {
    'A': 1,
    'B': 1,
    'C': 0,
    'D': 0,
}


def get_risk_assessment(neighborhood_id=None):
    """Return a cached risk assessment, optionally tuned for a neighborhood."""
    cache_key = str(neighborhood_id or 'citywide')
    now = time.time()
    cached = _risk_cache.get(cache_key)
    if cached and cached['expires_at'] > now:
        return {
            **cached['data'],
            'is_stale': False,
            'cache_expires_at': _isoformat_utc(cached['expires_at']),
        }

    neighborhood = _get_neighborhood_context(neighborhood_id)

    try:
        weather_payload = _fetch_poway_weather()
        observed_conditions, forecast_days = _parse_weather_payload(weather_payload)
        air_quality = _fetch_air_quality()
        result = _assemble_risk_response(observed_conditions, forecast_days, air_quality, neighborhood)
    except Exception as exc:
        if cached:
            return {
                **cached['data'],
                'is_stale': True,
                'cache_expires_at': _isoformat_utc(cached['expires_at']),
            }
        if isinstance(exc, RiskDataUnavailable):
            raise
        raise RiskDataUnavailable('weather fetch failed') from exc

    expires_at = now + current_app.config.get('RISK_CACHE_SECONDS', 1800)
    _risk_cache[cache_key] = {
        'data': result,
        'expires_at': expires_at,
    }
    return {
        **result,
        'is_stale': False,
        'cache_expires_at': _isoformat_utc(expires_at),
    }


def _fetch_poway_weather():
    lat = current_app.config.get('POWAY_LAT', 32.9628)
    lon = current_app.config.get('POWAY_LON', -117.0359)
    url = current_app.config.get('OPEN_METEO_URL', 'https://api.open-meteo.com/v1/forecast')
    params = {
        'latitude': lat,
        'longitude': lon,
        'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation',
        'hourly': 'precipitation',
        'daily': 'temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max',
        'temperature_unit': 'fahrenheit',
        'wind_speed_unit': 'mph',
        'precipitation_unit': 'inch',
        'forecast_days': 6,
        'past_days': 7,
        'timezone': 'America/Los_Angeles',
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def _fetch_air_quality():
    lat = current_app.config.get('POWAY_LAT', 32.9628)
    lon = current_app.config.get('POWAY_LON', -117.0359)
    url = current_app.config.get('OPEN_METEO_AIR_QUALITY_URL', 'https://air-quality-api.open-meteo.com/v1/air-quality')
    params = {
        'latitude': lat,
        'longitude': lon,
        'current': 'us_aqi,pm2_5,pm10',
        'timezone': 'America/Los_Angeles',
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        current = response.json().get('current', {})
        return {
            'us_aqi': current.get('us_aqi'),
            'pm2_5': current.get('pm2_5'),
            'pm10': current.get('pm10'),
        }
    except Exception:
        return {'us_aqi': None, 'pm2_5': None, 'pm10': None}


def _parse_weather_payload(payload):
    if not isinstance(payload, dict):
        raise RiskDataUnavailable('weather payload missing')

    current = payload.get('current') or {}
    daily = payload.get('daily') or {}
    hourly = payload.get('hourly') or {}

    required_current = (
        current.get('temperature_2m'),
        current.get('relative_humidity_2m'),
        current.get('wind_speed_10m'),
        current.get('precipitation'),
        current.get('time'),
    )
    if any(value is None for value in required_current):
        raise RiskDataUnavailable('weather payload incomplete')

    current_time = _parse_iso_datetime(current['time'])
    hourly_precip = _build_hourly_precip_series(hourly, current_time)
    if not hourly_precip:
        raise RiskDataUnavailable('hourly precipitation missing')

    observed_conditions = {
        'observed_at': current['time'],
        'temp_f': round(current['temperature_2m'], 1),
        'temperature_f': round(current['temperature_2m'], 1),
        'humidity': round(current['relative_humidity_2m'], 1),
        'wind_mph': round(current['wind_speed_10m'], 1),
        'precip_1hr_in': round(current['precipitation'], 2),
        'precip_in': round(current['precipitation'], 2),
        'precip_48hr_in': round(_sum_recent_precipitation(hourly_precip, hours=48), 2),
        'rain_7d_in': round(_sum_recent_precipitation(hourly_precip, hours=24 * 7), 2),
    }

    forecast_days = []
    dates = daily.get('time', [])
    max_temps = daily.get('temperature_2m_max', [])
    min_temps = daily.get('temperature_2m_min', [])
    precip = daily.get('precipitation_sum', [])
    max_wind = daily.get('wind_speed_10m_max', [])

    for index, date_value in enumerate(dates[:5]):
        forecast_days.append({
            'date': date_value,
            'temp_max_f': round(max_temps[index], 1) if index < len(max_temps) and max_temps[index] is not None else observed_conditions['temp_f'],
            'temp_min_f': round(min_temps[index], 1) if index < len(min_temps) and min_temps[index] is not None else observed_conditions['temp_f'] - 10,
            'precip_in': round(precip[index], 2) if index < len(precip) and precip[index] is not None else 0,
            'wind_mph': round(max_wind[index], 1) if index < len(max_wind) and max_wind[index] is not None else observed_conditions['wind_mph'],
        })

    return observed_conditions, forecast_days


def _get_neighborhood_context(neighborhood_id):
    if not neighborhood_id:
        return None

    neighborhood = Neighborhood.query.get(neighborhood_id)
    if not neighborhood:
        return None

    return {
        'id': neighborhood.id,
        'name': neighborhood.name,
        'number': neighborhood.number,
        'zone': neighborhood.zone or 'B',
    }


def compute_fire_risk(conditions, neighborhood=None):
    score = 1
    if conditions['temp_f'] >= 95:
        score += 4
    elif conditions['temp_f'] >= 85:
        score += 2
    elif conditions['temp_f'] >= 75:
        score += 1
    if conditions['humidity'] <= 20:
        score += 3
    elif conditions['humidity'] <= 30:
        score += 1
    elif conditions['humidity'] <= 40:
        score += 1
    if conditions['wind_mph'] >= 25:
        score += 2
    elif conditions['wind_mph'] >= 15:
        score += 1
    elif conditions['wind_mph'] >= 10:
        score += 1
    if conditions['rain_7d_in'] <= 0.1:
        score += 2
    elif conditions['rain_7d_in'] <= 0.4:
        score += 1

    if neighborhood:
        score += ZONE_FIRE_BONUS.get(neighborhood.get('zone'), 0)

    return max(0, min(score, 10))


def compute_flood_risk(conditions, neighborhood=None):
    score = 0
    if conditions['precip_48hr_in'] >= 0.1 or conditions['rain_7d_in'] >= 0.25:
        score += 1
    if conditions['precip_1hr_in'] >= 0.5:
        score += 4
    elif conditions['precip_1hr_in'] >= 0.2:
        score += 2
    if conditions['precip_48hr_in'] >= 1.0:
        score += 3
    elif conditions['precip_48hr_in'] >= 0.5:
        score += 1
    if conditions['rain_7d_in'] >= 1.5:
        score += 2

    if neighborhood:
        score += ZONE_FLOOD_BONUS.get(neighborhood.get('zone'), 0)

    return max(0, min(score, 10))


def compute_heat_risk(conditions):
    temp_f = conditions['temp_f']
    humidity = conditions['humidity']

    heat_index = (
        -42.379
        + 2.04901523 * temp_f
        + 10.14333127 * humidity
        - 0.22475541 * temp_f * humidity
        - 0.00683783 * temp_f * temp_f
        - 0.05481717 * humidity * humidity
        + 0.00122874 * temp_f * temp_f * humidity
        + 0.00085282 * temp_f * humidity * humidity
        - 0.00000199 * temp_f * temp_f * humidity * humidity
    )

    heat_index = round(max(heat_index, temp_f), 1)
    if heat_index >= 103:
        score = 9
    elif heat_index >= 95:
        score = 7
    elif heat_index >= 85:
        score = 4
    elif heat_index >= 75:
        score = 1
    else:
        score = 1 if temp_f >= 80 else 0

    return {'heat_index_f': heat_index, 'score': score}


def build_wildfire_forecast(forecast_days, neighborhood=None):
    forecast = []
    zone_bonus = ZONE_FIRE_BONUS.get((neighborhood or {}).get('zone'), 0)

    for day in forecast_days:
        score = 0
        if day['temp_max_f'] >= 95:
            score += 4
        elif day['temp_max_f'] >= 85:
            score += 2
        if day['wind_mph'] >= 25:
            score += 3
        elif day['wind_mph'] >= 15:
            score += 1
        if day['precip_in'] <= 0.05:
            score += 2
        score += zone_bonus

        score = max(0, min(score, 10))
        forecast.append({
            'date': day['date'],
            'fire_score': score,
            'fire_level': _score_label(score),
            'temp_max_f': day['temp_max_f'],
            'wind_mph': day['wind_mph'],
            'precip_in': day['precip_in'],
        })

    return forecast


def build_anomaly_alerts(conditions, heat_data, air_quality, wildfire_forecast):
    alerts = []

    if conditions['wind_mph'] >= 25:
        alerts.append({
            'severity': 'high',
            'title': 'Strong wind conditions detected',
            'message': f'Winds are at {conditions["wind_mph"]} mph, which can accelerate wildfire spread.',
        })
    if air_quality.get('us_aqi') is not None and air_quality['us_aqi'] >= 100:
        alerts.append({
            'severity': 'high' if air_quality['us_aqi'] >= 150 else 'moderate',
            'title': 'Air quality alert',
            'message': f'US AQI is {air_quality["us_aqi"]}. Limit outdoor activity for vulnerable residents.',
        })
    if heat_data['heat_index_f'] >= 100:
        alerts.append({
            'severity': 'high',
            'title': 'Dangerous heat stress',
            'message': f'Heat index is {heat_data["heat_index_f"]}F. Check on seniors, children, and outdoor workers.',
        })
    if conditions['precip_1hr_in'] >= 0.5 or conditions['precip_48hr_in'] >= 1.0:
        alerts.append({
            'severity': 'moderate',
            'title': 'Flooding conditions',
            'message': 'Heavy recent rainfall may create localized flooding on roads and low-lying areas.',
        })

    next_critical = next((day for day in wildfire_forecast if day['fire_score'] >= 8), None)
    if next_critical:
        alerts.append({
            'severity': 'high',
            'title': 'Elevated wildfire forecast',
            'message': f'{next_critical["date"]} is forecast to reach {next_critical["fire_level"]} wildfire conditions.',
        })

    return alerts


def _assemble_risk_response(conditions, forecast_days, air_quality, neighborhood):
    fire_score = compute_fire_risk(conditions, neighborhood)
    flood_score = compute_flood_risk(conditions, neighborhood)
    heat_data = compute_heat_risk(conditions)
    wildfire_forecast = build_wildfire_forecast(forecast_days, neighborhood)
    anomaly_alerts = build_anomaly_alerts(conditions, heat_data, air_quality, wildfire_forecast)

    enriched_conditions = {
        **conditions,
        'heat_index_f': heat_data['heat_index_f'],
        'us_aqi': air_quality.get('us_aqi'),
        'pm2_5': air_quality.get('pm2_5'),
        'pm10': air_quality.get('pm10'),
    }

    return {
        'neighborhood': neighborhood,
        'fire_score': fire_score,
        'fire_level': _score_label(fire_score),
        'flood_score': flood_score,
        'flood_level': _score_label(flood_score),
        'heat_score': heat_data['score'],
        'heat_level': _score_label(heat_data['score']),
        'heat_index_f': heat_data['heat_index_f'],
        'conditions': enriched_conditions,
        'wildfire_forecast': wildfire_forecast,
        'forecast_days': forecast_days,
        'anomaly_alerts': anomaly_alerts,
        'updated_at': datetime.utcnow().isoformat(),
    }


def _score_label(score):
    if score <= 2:
        return 'LOW'
    if score <= 4:
        return 'MODERATE'
    if score <= 7:
        return 'HIGH'
    return 'CRITICAL'


def _parse_iso_datetime(value):
    return datetime.fromisoformat(str(value)).replace(tzinfo=None)


def _build_hourly_precip_series(hourly, current_time):
    times = hourly.get('time') or []
    precip = hourly.get('precipitation') or []
    series = []

    for index, time_value in enumerate(times):
        if index >= len(precip) or precip[index] is None:
            continue
        sample_time = _parse_iso_datetime(time_value)
        if sample_time > current_time:
            continue
        series.append((sample_time, float(precip[index] or 0)))

    return series


def _sum_recent_precipitation(hourly_precip, hours):
    if not hourly_precip:
        return 0

    cutoff = hourly_precip[-1][0] - timedelta(hours=hours - 1)
    return sum(value for sample_time, value in hourly_precip if sample_time >= cutoff)


def _isoformat_utc(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
