# app/models/operations.py
# Responsibility: Volunteer availability and neighborhood resource inventory models.

from datetime import datetime

from app import db


class VolunteerAvailability(db.Model):
    """Tracks residents or coordinators who can help during incidents."""

    __tablename__ = 'volunteer_availability'

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    neighborhood_id = db.Column(db.Integer, db.ForeignKey('neighborhoods.id'), nullable=True)
    availability_status = db.Column(db.String(20), nullable=False, default='available')
    skills_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    neighborhood = db.relationship('Neighborhood')


class ResourceInventory(db.Model):
    """Tracks emergency supplies available for a neighborhood or citywide pool."""

    __tablename__ = 'resource_inventory'

    id = db.Column(db.Integer, primary_key=True)
    neighborhood_id = db.Column(db.Integer, db.ForeignKey('neighborhoods.id'), nullable=True)
    resource_type = db.Column(db.String(80), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    unit = db.Column(db.String(30), nullable=False, default='items')
    is_available = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    neighborhood = db.relationship('Neighborhood')


class HouseholdPreparedness(db.Model):
    """One private preparedness record per existing resident account."""
    __tablename__ = 'household_preparedness'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    items = db.Column(db.JSON, nullable=False, default=dict)
    household_size = db.Column(db.Integer, nullable=False, default=1)
    meeting_point = db.Column(db.String(300), nullable=False, default='')
    evacuation_plan = db.Column(db.String(2000), nullable=False, default='')
    quiz_answers = db.Column(db.JSON, nullable=False, default=dict)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class VolunteerTask(db.Model):
    __tablename__ = 'volunteer_tasks'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(2000), nullable=False, default='')
    neighborhood_id = db.Column(db.Integer, db.ForeignKey('neighborhoods.id'), nullable=True)
    starts_at = db.Column(db.DateTime, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    claimed_count = db.Column(db.Integer, nullable=False, default=0)
    closed = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)


class TaskSignup(db.Model):
    __tablename__ = 'task_signups'
    task_id = db.Column(db.Integer, db.ForeignKey('volunteer_tasks.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ResidentCheckIn(db.Model):
    __tablename__ = 'resident_check_ins'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    neighborhood_id = db.Column(db.Integer, db.ForeignKey('neighborhoods.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    note = db.Column(db.String(1000), nullable=False, default='')
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SupplyDrive(db.Model):
    __tablename__ = 'supply_drives'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(2000), nullable=False, default='')
    unit = db.Column(db.String(30), nullable=False)
    goal = db.Column(db.Integer, nullable=False)
    received = db.Column(db.Integer, nullable=False, default=0)
    closed = db.Column(db.Boolean, nullable=False, default=False)


class SupplyPledge(db.Model):
    __tablename__ = 'supply_pledges'
    id = db.Column(db.Integer, primary_key=True)
    drive_id = db.Column(db.Integer, db.ForeignKey('supply_drives.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    fulfilled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class HazardReport(db.Model):
    __tablename__ = 'hazard_reports'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    neighborhood_id = db.Column(db.Integer, db.ForeignKey('neighborhoods.id'), nullable=False)
    category = db.Column(db.String(30), nullable=False)
    location = db.Column(db.String(300), nullable=False)
    description = db.Column(db.String(2000), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='open')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class WeeklyTip(db.Model):
    __tablename__ = 'weekly_tips'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(3000), nullable=False)
    threat = db.Column(db.String(20), nullable=False, default='general')
    week_start = db.Column(db.Date, nullable=False)
