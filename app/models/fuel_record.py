from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, DECIMAL, Text, CHAR
from sqlalchemy.orm import relationship
from .base import Base


class FuelRecord(Base):
    __tablename__ = 'fuel_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey('vehicles.id', ondelete='CASCADE'), nullable=False)
    refuel_datetime = Column(DateTime, nullable=False)
    odometer = Column(Integer, nullable=False)
    fuel_type = Column(String(15), nullable=False)
    volume_liters = Column(DECIMAL(7, 2), nullable=False)
    unit_price = Column(DECIMAL(10, 3), nullable=True)
    price_paid = Column(DECIMAL(12, 3), nullable=False)
    currency_code = Column(CHAR(3), nullable=False, default='CZK')
    unit_price_local = Column(DECIMAL(10, 3), nullable=True)
    price_local = Column(DECIMAL(12, 3), nullable=True)
    payment_method = Column(String(20), nullable=True)
    station_name = Column(String(100), nullable=True)
    full_tank = Column(Boolean, nullable=False, default=False)
    skipped_refuel = Column(Boolean, nullable=False, default=False)
    consumption = Column(DECIMAL(5, 2), nullable=True)
    note = Column(Text, nullable=True)

    # Napojení na tabulku vozidel
    vehicle = relationship('Vehicle', back_populates='fuel_records')

    def __repr__(self):
        return f"FuelRecord id={self.id} vehicle_id={self.vehicle_id} datetime={self.refuel_datetime}"