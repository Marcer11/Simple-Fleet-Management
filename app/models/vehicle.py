from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship
from .base import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True)
    brand = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    license_plate = Column(String(10))
    color = Column(String(30))
    color_hex = Column(String(7), default="#FFFFFF")
    is_active = Column(Boolean, default=True)

    # Vazba na záznamy o tankování
    fuel_records = relationship('FuelRecord', back_populates='vehicle', cascade='all, delete')

    def __repr__(self):
        return f"{self.id}: {self.brand} {self.model} ({self.license_plate})"