# app/routes/live.py
# Responsibility: serve aggregated "right now" Poway data to the
# chatbot and any other client that wants a single endpoint for
# weather + AQI + NWS alerts + fire-weather + sunrise/sunset.
#
# Design notes:
#   - GET only, public. The data is already public (NWS, Open-Meteo).
#   - 30-min server-side cache lives in live_service so this route
#     stays cheap under chatbot load.
#   - Errors return a structured 200 with ok=false rather than 5xx,
#     so the chatbot can degrade gracefully instead of breaking.

from flask import Blueprint, jsonify, current_app
from app.services import live_service

live_bp = Blueprint('live', __name__)


@live_bp.route('/live/conditions', methods=['GET'])
def get_live_conditions():
    """
    Purpose: return aggregated current conditions for Poway.
    Algorithm:
      1. Delegate to live_service.get_live_conditions()
      2. Wrap with ok=True
      3. Catch any unexpected error → return ok=false 200
    """
    try:
        data = live_service.get_live_conditions()
        return jsonify({'ok': True, **data}), 200
    except Exception:
        try:
            current_app.logger.exception('live.get_live_conditions failed')
        except Exception:
            pass
        # Soft failure — chatbot reads `ok: false` and skips the block.
        return jsonify({'ok': False, 'error': 'Live service unavailable.'}), 200
