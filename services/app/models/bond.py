from extensions import db
from sqlalchemy import Column, ForeignKey, Integer, String, desc
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import datetime

class Asset(db.Model):
    __tablename__ = "asset"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    period = db.Column(db.Integer, nullable=False)
    # Relationship to BondYield
    historical_bond_yields = relationship('BondYield', back_populates='asset')
    realtime_bond_yields = relationship('BondYieldRealtime', back_populates='asset')

    def __init__(self, name, period):
        self.name = name
        self.period = int(period)
        db.session.add(self)
        db.session.commit()

class BondYield(db.Model):
    __tablename__ = "bond_yield"
    # id = db.Column(db.String(50), primary_key=True, nullable=False)
    date = db.Column(db.Date, primary_key=True, nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), primary_key=True, nullable=False)
    bond_yield = db.Column(db.Float, nullable=False)
    ref_id = db.Column(db.Integer, nullable=False)
    # Relationship to Country
    asset = relationship('Asset')

    def __init__(self, date, asset_id, bond_yield, ref_id):
        # self.id = f"{datetime.datetime.strftime(date, "%Y-%m-%d")}_{country_name}_{period}"
        self.date = date
        self.asset_id = int(asset_id)
        self.bond_yield = float(bond_yield)
        self.ref_id = int(ref_id)
        db.session.add(self)
        db.session.commit()

class BondYieldRealtime(db.Model):
    __tablename__ = "bond_yield_realtime"
    # id = db.Column(db.String(50), primary_key=True, nullable=False)
    datetime = db.Column(db.DateTime, primary_key=True, nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), primary_key=True, nullable=False)
    bond_yield = db.Column(db.Float, nullable=False)
    timeframe = db.Column(db.Integer, nullable=False)
    # Relationship to Country
    asset = relationship('Asset')

    def __init__(self, datetime, asset_id, bond_yield, timeframe):
        # self.id = f"{datetime.datetime.strftime(date, "%Y-%m-%d")}_{country_name}_{period}"
        self.datetime = datetime
        self.asset_id = int(asset_id)
        self.bond_yield = float(bond_yield)
        self.timeframe = timeframe
        db.session.add(self)
        db.session.commit()


