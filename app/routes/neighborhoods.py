# app/routes/neighborhoods.py
# Responsibility: Neighborhood API endpoints — list, detail, lookup by point/address/name.

from flask import Blueprint, request, jsonify
from app.services import neighborhood_service
from app.utils.errors import error_response

neighborhoods_bp = Blueprint('neighborhoods', __name__)


@neighborhoods_bp.route('/neighborhoods', methods=['GET'])
def get_neighborhoods():
    """Return all neighborhoods for the map and registration dropdown."""
    neighborhoods = neighborhood_service.get_all_neighborhoods()
    return jsonify({'neighborhoods': neighborhoods}), 200


@neighborhoods_bp.route('/neighborhoods/<int:neighborhood_id>', methods=['GET'])
def get_neighborhood(neighborhood_id):
    """Return a single neighborhood by ID."""
    n = neighborhood_service.get_neighborhood_by_id(neighborhood_id)
    if not n:
        return error_response('NOT_FOUND', 404)
    return jsonify({'neighborhood': n}), 200


@neighborhoods_bp.route('/neighborhoods/lookup', methods=['GET'])
def lookup_neighborhood():
    """Find a neighborhood by GPS point, street address, name, or number."""
    address = request.args.get('address', '').strip()
    lat = request.args.get('lat')
    lng = request.args.get('lng')
    result = neighborhood_service.lookup_neighborhood(address, lat=lat, lng=lng)
    return jsonify(result), 200
