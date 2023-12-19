from extensions import db
from sqlalchemy import Column, ForeignKey, Integer, String, desc
import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

class BondYield(db.Model):
    __tablename__ = "bond_yield"
    id = db.Column(db.Integer, primary_key=True, default=lambda: uuid.uuid4().hex, nullable=False)
    date = db.Column(db.Date, nullable=False)
    country_id = db.Column(db.String(80), db.ForeignKey('country.id'), nullable=False)
    period = db.Column(db.Integer(), nullable=False)
    bond_yield = db.Column(db.String(50), nullable=False)
    # Relationship to Country
    country = relationship('Country')

    def __init__(self, date, country_name, bond_yield, period):
        self.date = date
        country = Country.query.filter_by(name=country_name).first()
        if not country:
            # Handle the case where the country does not exist in the database
            super().__init__(country_name)
        self.country_id = Country.query.filter_by(name=country_name).first()
        self.bond_yield = bond_yield
        self.period = period


class Country(db.Model):
    __tablename__ = "country"
    id = db.Column(db.String(80), primary_key=True, autoincrement=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    # Relationship to BondYield
    bond_yields = relationship('BondYield', back_populates='country')

    def __init__(self, name):
        self.name = name
        db.session.add(self)
        db.session.commit()

    @classmethod
    def find_by_name(cls, name):
        return cls.query.filter_by(name=name).first()
