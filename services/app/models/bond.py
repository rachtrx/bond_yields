from extensions import db
from sqlalchemy import Column, ForeignKey, Integer, String, desc
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import datetime

class Country(db.Model):
    __tablename__ = "country"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    # Relationship to BondYield
    bond_yields = relationship('BondYield', back_populates='country')

    def __init__(self, name):
        self.name = name
        db.session.add(self)
        db.session.commit()

class BondYield(db.Model):
    __tablename__ = "bond_yield"
    id = db.Column(db.String(50), primary_key=True, nullable=False)
    date = db.Column(db.Date, nullable=False)
    country_id = db.Column(db.Integer, db.ForeignKey('country.id'), nullable=False)
    period = db.Column(db.Integer, nullable=False)
    bond_yield = db.Column(db.String(50), nullable=False)
    ref_id = db.Column(db.Integer, nullable=False)
    # Relationship to Country
    country = relationship('Country')

    def __init__(self, date, country_name, country_id, bond_yield, period, ref_id):
        self.id = f"{datetime.datetime.strftime(date, "%Y-%m-%d")}_{country_name}_{period}"
        self.date = date
        self.country_id = int(country_id)
        self.bond_yield = float(bond_yield)
        self.period = int(period)
        self.ref_id = int(ref_id)
        db.session.add(self)
        db.session.commit()
