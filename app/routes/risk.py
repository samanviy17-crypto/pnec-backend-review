# app/routes/risk.py
# Responsibility: Risk API endpoint — returns current fire/flood/heat assessment.

from flask import Blueprint, jsonify, request, current_app
from app.services import risk_service
from app.services.risk_service import RiskDataUnavailable
from app.utils.errors import error_response

risk_bp = Blueprint('risk', __name__)


@risk_bp.route('/risk', methods=['GET'])
def get_risk():
    """
    Purpose: Return the current risk assessment for Poway (fire, flood, heat).
    Responses are cached for 30 minutes to avoid hammering Open-Meteo.
    Algorithm:
    1. Delegate to risk_service.get_risk_assessment()
    2. Return JSON payload
    3. Catch any unexpected errors and return 503
    """
    try:
        neighborhood_id = request.args.get('neighborhood_id', type=int)
        assessment = risk_service.get_risk_assessment(neighborhood_id=neighborhood_id)
        return jsonify(assessment), 200
    except RiskDataUnavailable:
        try:
            current_app.logger.warning('risk.get_risk unavailable')
        except Exception:
            pass
        return error_response('SERVER_ERROR', 503, {'detail': 'Risk service unavailable.'})
    except Exception:
        # SECURITY: do NOT pass str(e) to the client — exception messages
        # from Open-Meteo or SQLAlchemy frequently include URLs (with
        # API keys), file paths, env-var names, etc. Log server-side.
        try:
            current_app.logger.exception('risk.get_risk failed')
        except Exception:
            pass
        return error_response('SERVER_ERROR', 503, {'detail': 'Risk service unavailable.'})
