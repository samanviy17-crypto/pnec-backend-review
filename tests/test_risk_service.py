from datetime import datetime, timedelta
import time

import pytest
import requests

from app.services import risk_service


@pytest.fixture(autouse=True)
def clear_risk_cache():
    risk_service._risk_cache.clear()
    yield
    risk_service._risk_cache.clear()


def test_parse_weather_payload_uses_observed_hourly_precipitation():
    current_time = datetime(2026, 5, 19, 12, 0, 0)
    hourly_times = [
        (current_time - timedelta(hours=167 - index)).isoformat(timespec='minutes')
        for index in range(168)
    ]
    hourly_precip = [0.05] * 168
    hourly_precip[-1] = 0.25

    payload = {
        'current': {
            'time': current_time.isoformat(timespec='minutes'),
            'temperature_2m': 88,
            'relative_humidity_2m': 24,
            'wind_speed_10m': 16,
            'precipitation': 0.25,
        },
        'hourly': {
            'time': hourly_times,
            'precipitation': hourly_precip,
        },
        'daily': {
            'time': ['2026-05-19', '2026-05-20', '2026-05-21', '2026-05-22', '2026-05-23'],
            'temperature_2m_max': [90, 91, 92, 93, 94],
            'temperature_2m_min': [64, 65, 66, 67, 68],
            'precipitation_sum': [2.0, 3.0, 4.0, 5.0, 6.0],
            'wind_speed_10m_max': [14, 15, 16, 17, 18],
        },
    }

    observed_conditions, forecast_days = risk_service._parse_weather_payload(payload)

    assert observed_conditions['precip_1hr_in'] == 0.25
    assert observed_conditions['precip_48hr_in'] == 2.6
    assert observed_conditions['rain_7d_in'] == 8.6
    assert forecast_days[0]['precip_in'] == 2.0


def test_get_risk_assessment_returns_stale_cached_payload_when_upstream_fails(app, monkeypatch):
    cached_data = {
        'fire_score': 4,
        'flood_score': 1,
        'heat_score': 2,
        'conditions': {'temperature_f': 75},
        'updated_at': '2026-05-19T18:00:00',
    }
    risk_service._risk_cache['citywide'] = {
        'data': cached_data,
        'expires_at': time.time() - 10,
    }

    def fail_fetch():
        raise requests.RequestException('boom')

    monkeypatch.setattr(risk_service, '_fetch_poway_weather', fail_fetch)

    with app.app_context():
        result = risk_service.get_risk_assessment()

    assert result['is_stale'] is True
    assert result['updated_at'] == cached_data['updated_at']
    assert 'cache_expires_at' in result


def test_risk_route_returns_503_without_cached_data_on_upstream_failure(app, client, monkeypatch):
    def fail_fetch():
        raise requests.RequestException('boom')

    monkeypatch.setattr(risk_service, '_fetch_poway_weather', fail_fetch)

    response = client.get('/api/risk')

    assert response.status_code == 503
    body = response.get_json()
    assert body['error'] == 'SERVER_ERROR'
