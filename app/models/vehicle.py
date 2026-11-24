from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime, Text, CHAR, DECIMAL, ForeignKey, UniqueConstraint, func
)
from sqlalchemy.orm import relationship
from .base import Base


# Úrovně přístupu k vozidlu (vyšší číslo = více práv)
ROLE_VIEWER = "viewer"
ROLE_EDITOR = "editor"
ROLE_OWNER = "owner"
ROLE_LEVELS = {ROLE_VIEWER: 1, ROLE_EDITOR: 2, ROLE_OWNER: 3}
SHARE_ROLES = {ROLE_VIEWER: "Jen náhled", ROLE_EDITOR: "Úpravy"}


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    brand = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    production_year = Column(Integer, nullable=True)
    color = Column(String(30))
    color_hex = Column(CHAR(7), nullable=False, default="#FFFFFF")
    license_plate = Column(String(10), index=True)
    vin = Column(CHAR(17), nullable=True, index=True)
    note = Column(Text, nullable=True)
    purchase_date = Column(Date, nullable=True)
    sale_date = Column(Date, nullable=True)
    purchase_price = Column(DECIMAL(12, 2), nullable=True)  # Kč
    sale_price = Column(DECIMAL(12, 2), nullable=True)      # Kč
    is_active = Column(Boolean, nullable=False, default=True)

    owner = relationship("User", back_populates="vehicles")
    shares = relationship("VehicleShare", back_populates="vehicle", cascade="all, delete-orphan")
    fuel_records = relationship("FuelRecord", back_populates="vehicle", cascade="all, delete-orphan")
    service_records = relationship("ServiceRecord", back_populates="vehicle", cascade="all, delete-orphan")
    service_intervals = relationship("ServiceInterval", back_populates="vehicle", cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="vehicle", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="vehicle", cascade="all, delete-orphan")
    notes = relationship("VehicleNote", back_populates="vehicle", cascade="all, delete-orphan")

    @property
    def display_name(self):
        name = f"{self.brand} {self.model}"
        return f"{name} ({self.license_plate})" if self.license_plate else name

    @property
    def value_loss(self):
        """Ztráta hodnoty (nákup - prodej), pokud známe obě ceny."""
        if self.purchase_price is None or self.sale_price is None:
            return None
        return self.purchase_price - self.sale_price

    def __repr__(self):
        return f"{self.id}: {self.brand} {self.model} ({self.license_plate})"


class VehicleShare(Base):
    """Sdílení vozidla s dalším uživatelem."""
    __tablename__ = "vehicle_shares"
    __table_args__ = (UniqueConstraint("vehicle_id", "user_id", name="uq_vehicle_shares_vehicle_user"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(10), nullable=False, default=ROLE_VIEWER)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    vehicle = relationship("Vehicle", back_populates="shares")
    user = relationship("User", back_populates="shares")
