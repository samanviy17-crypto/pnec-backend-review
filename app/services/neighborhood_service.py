# app/services/neighborhood_service.py
# Responsibility: Neighborhood business logic — fetch, seed, and address lookup.

import json

import requests
from flask import current_app

from app import db
from app.models.neighborhood import Neighborhood


def get_all_neighborhoods():
    """
    Purpose: Return all neighborhoods as a list of dicts.
    @returns {list} All neighborhood dicts ordered by number
    """
    neighborhoods = Neighborhood.query.order_by(Neighborhood.number).all()
    return [n.to_dict() for n in neighborhoods]


def get_neighborhood_by_id(neighborhood_id):
    """
    Purpose: Fetch a single neighborhood by primary key.
    @param {int} neighborhood_id - The neighborhood PK
    @returns {dict|None} Neighborhood dict or None if not found
    """
    n = Neighborhood.query.get(neighborhood_id)
    return n.to_dict() if n else None


def lookup_neighborhood_by_name(query_text):
    """
    Purpose: Search neighborhoods by name or number (for address/name search bar).
    @param {str} query_text - Search string from the user
    @returns {list} List of matching neighborhood dicts (up to 10)
    Algorithm:
    1. Sanitize query
    2. Search by name (LIKE) and number (exact if numeric)
    3. Return top 10 matches
    """
    if not query_text or len(query_text.strip()) < 1:
        return []

    term = f'%{query_text.strip()}%'
    matches = Neighborhood.query.filter(Neighborhood.name.ilike(term)).limit(10).all()

    # Also try exact number match if query is numeric
    if query_text.strip().isdigit():
        number_match = Neighborhood.query.filter_by(number=int(query_text.strip())).first()
        if number_match and number_match not in matches:
            matches.insert(0, number_match)

    return [n.to_dict() for n in matches]


def lookup_neighborhood(query_text=None, lat=None, lng=None):
    """
    Purpose: Locate a neighborhood by GPS point, street address, name, or number.
    @param {str|None} query_text - Address, neighborhood name, or neighborhood number
    @param {float|None} lat - Latitude from browser GPS or geocoding
    @param {float|None} lng - Longitude from browser GPS or geocoding
    @returns {dict} Lookup result with one matching neighborhood or search results
    Algorithm:
    1. If latitude/longitude are provided, match them against neighborhood polygons
    2. If an address is provided, geocode it and match the geocoded point
    3. Fall back to existing name/number search
    """
    point = _coerce_point(lat, lng)
    if point:
        neighborhood = find_neighborhood_containing_point(point[0], point[1])
        return {
            'neighborhood': neighborhood.to_dict() if neighborhood else None,
            'results': [neighborhood.to_dict()] if neighborhood else [],
            'coordinates': {'lat': point[0], 'lng': point[1]},
            'source': 'coordinates',
        }

    query_text = (query_text or '').strip()
    if query_text:
        geocoded_point = geocode_address(query_text)
        if geocoded_point:
            neighborhood = find_neighborhood_containing_point(
                geocoded_point['lat'],
                geocoded_point['lng'],
            )
            if neighborhood:
                return {
                    'neighborhood': neighborhood.to_dict(),
                    'results': [neighborhood.to_dict()],
                    'coordinates': geocoded_point,
                    'source': 'geocoded_address',
                }

        results = lookup_neighborhood_by_name(query_text)
        return {
            'neighborhood': results[0] if len(results) == 1 else None,
            'results': results,
            'coordinates': geocoded_point,
            'source': 'name_or_number',
        }

    return {'neighborhood': None, 'results': [], 'coordinates': None, 'source': None}


def find_neighborhood_containing_point(lat, lng):
    """
    Purpose: Return the first neighborhood whose polygon contains a point.
    @param {float} lat - Latitude
    @param {float} lng - Longitude
    @returns {Neighborhood|None} Matching neighborhood row
    """
    neighborhoods = Neighborhood.query.filter(
        Neighborhood.polygon_coords_json.isnot(None),
        Neighborhood.polygon_coords_json != '',
    ).order_by(Neighborhood.number).all()

    for neighborhood in neighborhoods:
        if _neighborhood_contains_point(neighborhood, lat, lng):
            return neighborhood

    return None


def geocode_address(address):
    """
    Purpose: Convert a Poway-area street address into latitude/longitude.
    Uses the public US Census geocoder, which does not require an API key.
    """
    if not address or len(address.strip()) < 3:
        return None

    query = address.strip()
    if 'poway' not in query.lower():
        query = f'{query}, Poway, CA'

    try:
        response = requests.get(
            'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress',
            params={
                'address': query,
                'benchmark': 'Public_AR_Current',
                'format': 'json',
            },
            headers={'User-Agent': 'PNEC neighborhood lookup'},
            timeout=4,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        current_app.logger.warning('Address geocoding failed: %s', exc)
        return None

    matches = data.get('result', {}).get('addressMatches', [])
    if not matches:
        return None

    coordinates = matches[0].get('coordinates') or {}
    lat = coordinates.get('y')
    lng = coordinates.get('x')
    point = _coerce_point(lat, lng)
    if not point:
        return None

    return {'lat': point[0], 'lng': point[1], 'matched_address': matches[0].get('matchedAddress')}


def _coerce_point(lat, lng):
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return None

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None

    return lat, lng


def _neighborhood_contains_point(neighborhood, lat, lng):
    polygons = _parse_polygon_coords(neighborhood.polygon_coords_json)
    for polygon in polygons:
        if not polygon:
            continue

        outer_ring = polygon[0]
        hole_rings = polygon[1:]
        if _point_in_ring(lat, lng, outer_ring) and not any(
            _point_in_ring(lat, lng, hole) for hole in hole_rings
        ):
            return True

    return False


def _parse_polygon_coords(raw_coords):
    """
    Purpose: Normalize stored polygon JSON into [polygon][ring][lat,lng].
    Supports plain [[lat,lng], ...], [[[lat,lng], ...]], and GeoJSON
    Polygon/MultiPolygon coordinate objects.
    """
    if not raw_coords:
        return []

    try:
        parsed = json.loads(raw_coords) if isinstance(raw_coords, str) else raw_coords
    except (TypeError, ValueError):
        return []

    if isinstance(parsed, dict):
        geometry = parsed.get('geometry') if parsed.get('type') == 'Feature' else parsed
        geo_type = geometry.get('type')
        coords = geometry.get('coordinates')
        if geo_type == 'Polygon':
            return [_normalize_geojson_polygon(coords)]
        if geo_type == 'MultiPolygon':
            return [_normalize_geojson_polygon(polygon) for polygon in coords or []]
        return []

    return _normalize_plain_polygon(parsed)


def _normalize_geojson_polygon(coords):
    return [[_lon_lat_to_lat_lng(point) for point in ring] for ring in coords or []]


def _normalize_plain_polygon(coords):
    if not isinstance(coords, list) or not coords:
        return []

    if _looks_like_coordinate(coords[0]):
        ring = [_coerce_coordinate(point) for point in coords if _coerce_coordinate(point)]
        return [[ring]]

    if coords and isinstance(coords[0], list) and coords[0] and _looks_like_coordinate(coords[0][0]):
        rings = [[_coerce_coordinate(point) for point in ring if _coerce_coordinate(point)] for ring in coords]
        return [rings]

    return []


def _looks_like_coordinate(value):
    return isinstance(value, (list, tuple)) and len(value) >= 2


def _coerce_coordinate(point):
    try:
        lat = float(point[0])
        lng = float(point[1])
    except (TypeError, ValueError, IndexError):
        return None

    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return lat, lng

    return None


def _lon_lat_to_lat_lng(point):
    try:
        lng = float(point[0])
        lat = float(point[1])
    except (TypeError, ValueError, IndexError):
        return None

    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return lat, lng

    return None


def _point_in_ring(lat, lng, ring):
    clean_ring = [point for point in ring if point]
    if len(clean_ring) < 3:
        return False

    inside = False
    j = len(clean_ring) - 1

    for i, point in enumerate(clean_ring):
        yi, xi = point
        yj, xj = clean_ring[j]
        intersects = ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i

    return inside


def seed_neighborhoods():
    """
    Purpose: Populate the neighborhoods table with the ~60 Poway neighborhoods.
    Only runs if the table is empty. Coordinator data is placeholder.
    @returns {int} Number of records inserted
    Algorithm:
    1. Check if any rows exist — skip if so
    2. Insert all neighborhood seed records
    3. Commit and return count
    """
    if Neighborhood.query.first():
        return 0

    from pathlib import Path
    # Public number/name/zone metadata only, reconciled with the approved map.
    # Never infer geographic boundary polygons from image-space hotspot coordinates.
    seed_data=json.loads((Path(__file__).resolve().parents[1]/'data/neighborhoods.json').read_text())

    records = []
    for d in seed_data:
        records.append(Neighborhood(
            number=d['number'],
            name=d['name'],
            zone=d['zone'],
            coordinator_name='[Coordinator TBD]',
            coordinator_email=current_app.config.get('PUBLIC_CONTACT_EMAIL') or None,
        ))

    db.session.add_all(records)
    db.session.commit()
    return len(records)
