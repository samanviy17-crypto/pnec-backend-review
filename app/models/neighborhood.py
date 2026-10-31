# app/models/neighborhood.py
# Responsibility: Neighborhood database model — zones, coordinator assignments, map polygon data.

from app import db


class Neighborhood(db.Model):
    """A named Poway neighborhood with coordinator and map data."""

    __tablename__ = 'neighborhoods'

    id                   = db.Column(db.Integer,     primary_key=True)
    name                 = db.Column(db.String(100), nullable=False)
    number               = db.Column(db.Integer,     nullable=True)     # PNEC neighborhood number
    coordinator_name     = db.Column(db.String(100), nullable=True)
    coordinator_email    = db.Column(db.String(255), nullable=True)
    ham_radio_operator   = db.Column(db.String(100), nullable=True)
    zone                 = db.Column(db.String(10),  nullable=True)     # A, B, C, D (evacuation zones)
    polygon_coords_json  = db.Column(db.Text,        nullable=True)     # JSON array of [lat, lon] pairs

    # Relationships
    residents = db.relationship('User', back_populates='neighborhood',
                                foreign_keys='User.neighborhood_id', lazy='dynamic')

    def to_dict(self):
        """Return a JSON-serializable dict for API responses."""
        return {
            'id':                  self.id,
            'name':                self.name,
            'number':              self.number,
            'coordinator_name':    self.coordinator_name,
            'coordinator_email':   self.coordinator_email,
            'ham_radio_operator':  self.ham_radio_operator,
            'zone':                self.zone,
            'polygon_coords_json': self.polygon_coords_json,
        }

    def __repr__(self):
        return f'<Neighborhood #{self.number} {self.name}>'
