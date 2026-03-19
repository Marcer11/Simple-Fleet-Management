from sqlalchemy import Column, Integer, String, Boolean
from .base import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True)
    brand = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    license_plate = Column(String(10))
    color = Column(String(30))
    is_active = Column(Boolean, default=True)

    def __repr__(self):
        return f"{self.id}: {self.brand} {self.model} ({self.license_plate})"