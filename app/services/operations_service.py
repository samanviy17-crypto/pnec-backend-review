# app/services/operations_service.py
# Responsibility: Volunteer/resource optimization snapshot for admin operations dashboard.

from app import db
from app.models.neighborhood import Neighborhood
from app.models.operations import VolunteerAvailability, ResourceInventory
from app.models.user import User

ZONE_WEIGHT = {
    'A': 1.35,
    'B': 1.15,
    'C': 1.0,
    'D': 0.9,
}


def get_operations_snapshot():
    """Return neighborhood-level staffing and supply recommendations."""
    neighborhoods = Neighborhood.query.order_by(Neighborhood.number).all()

    resident_rows = (
        db.session.query(User.neighborhood_id, db.func.count(User.id))
        .filter(User.neighborhood_id.isnot(None), User.is_active.is_(True))
        .group_by(User.neighborhood_id)
        .all()
    )
    resident_counts = {neighborhood_id: count for neighborhood_id, count in resident_rows}

    volunteer_rows = (
        db.session.query(VolunteerAvailability.neighborhood_id, db.func.count(VolunteerAvailability.id))
        .filter(VolunteerAvailability.availability_status == 'available')
        .group_by(VolunteerAvailability.neighborhood_id)
        .all()
    )
    volunteer_counts = {neighborhood_id: count for neighborhood_id, count in volunteer_rows}

    coordinator_rows = (
        db.session.query(User.neighborhood_id, db.func.count(User.id))
        .filter(User.neighborhood_id.isnot(None), User.is_active.is_(True), User.role.in_(('coordinator', 'staff', 'admin')))
        .group_by(User.neighborhood_id)
        .all()
    )
    for neighborhood_id, count in coordinator_rows:
        volunteer_counts[neighborhood_id] = volunteer_counts.get(neighborhood_id, 0) + count

    resource_rows = (
        db.session.query(ResourceInventory.neighborhood_id, db.func.sum(ResourceInventory.quantity))
        .filter(ResourceInventory.is_available.is_(True))
        .group_by(ResourceInventory.neighborhood_id)
        .all()
    )
    resource_counts = {neighborhood_id: int(quantity or 0) for neighborhood_id, quantity in resource_rows}

    recommendations = []
    for neighborhood in neighborhoods:
        resident_total = resident_counts.get(neighborhood.id, 0)
        volunteer_total = volunteer_counts.get(neighborhood.id, 0)
        resource_total = resource_counts.get(neighborhood.id, 0)
        zone_weight = ZONE_WEIGHT.get(neighborhood.zone or 'B', 1.0)
        pressure_score = round((resident_total * zone_weight) - (volunteer_total * 8) - (resource_total * 0.35), 1)

        recommendations.append({
            'id': neighborhood.id,
            'number': neighborhood.number,
            'name': neighborhood.name,
            'zone': neighborhood.zone,
            'resident_count': resident_total,
            'volunteer_count': volunteer_total,
            'resource_units': resource_total,
            'pressure_score': pressure_score,
            'priority': _priority_label(pressure_score),
            'recommended_action': _recommended_action(pressure_score, volunteer_total, resource_total),
        })

    recommendations.sort(key=lambda item: item['pressure_score'], reverse=True)
    return recommendations


def seed_operations_data():
    """Insert a few starter resources/volunteers so the dashboard is usable on first run."""
    if VolunteerAvailability.query.first() or ResourceInventory.query.first():
        return

    sample_neighborhoods = Neighborhood.query.order_by(Neighborhood.number).limit(4).all()
    if not sample_neighborhoods:
        return

    for neighborhood in sample_neighborhoods:
        db.session.add(VolunteerAvailability(
            display_name=f'Volunteer Lead #{neighborhood.number}',
            email=f'volunteer{neighborhood.number}@powaynec.com',
            neighborhood_id=neighborhood.id,
            availability_status='available',
            skills_json='["check-ins","wellness","logistics"]',
        ))

    for index, neighborhood in enumerate(sample_neighborhoods):
        db.session.add(ResourceInventory(
            neighborhood_id=neighborhood.id,
            resource_type='Go-bags',
            quantity=max(5, 18 - (index * 3)),
            unit='kits',
            notes='Starter emergency kits available for vulnerable residents',
        ))
        db.session.add(ResourceInventory(
            neighborhood_id=neighborhood.id,
            resource_type='N95 masks',
            quantity=max(20, 90 - (index * 12)),
            unit='masks',
            notes='Smoke readiness inventory',
        ))

    db.session.commit()


def _priority_label(pressure_score):
    if pressure_score >= 55:
        return 'Immediate'
    if pressure_score >= 30:
        return 'High'
    if pressure_score >= 10:
        return 'Moderate'
    return 'Stable'


def _recommended_action(pressure_score, volunteer_total, resource_total):
    if pressure_score >= 55:
        return 'Stage extra volunteers and move supply cache into this neighborhood first.'
    if volunteer_total == 0:
        return 'Recruit or assign a coordinator-level volunteer before the next incident.'
    if resource_total < 25:
        return 'Rebalance emergency kits and masks from lower-pressure neighborhoods.'
    if pressure_score >= 10:
        return 'Monitor demand and pre-position a small support team.'
    return 'No immediate reallocation needed.'
