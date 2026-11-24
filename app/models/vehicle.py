from datetime import date

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

# Druh vozidla - podle něj nákres a pozice pneumatik (motorka má jen přední a zadní kolo)
KIND_CAR = "car"
KIND_MOTO = "moto"
VEHICLE_KINDS = {KIND_CAR: "Auto", KIND_MOTO: "Motorka"}


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    brand = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    kind = Column(String(10), nullable=False, default=KIND_CAR, server_default=KIND_CAR)
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
    purchase_odometer = Column(Integer, nullable=True)      # km při nákupu
    sale_odometer = Column(Integer, nullable=True)          # km při prodeji
    is_active = Column(Boolean, nullable=False, default=True)
    # Půjčené vozidlo (z půjčovny nebo od známých) - k němu se evidují jednotlivá půjčení
    is_rental = Column(Boolean, nullable=False, default=False, server_default="0")
    # Povolené rozměry pneumatik dle technického průkazu - jeden na řádek ("205/55 R16 91V")
    tire_sizes = Column(String(500), nullable=True)

    owner = relationship("User", back_populates="vehicles")
    shares = relationship("VehicleShare", back_populates="vehicle", cascade="all, delete-orphan")
    fuel_records = relationship("FuelRecord", back_populates="vehicle", cascade="all, delete-orphan")
    service_records = relationship("ServiceRecord", back_populates="vehicle", cascade="all, delete-orphan")
    service_intervals = relationship("ServiceInterval", back_populates="vehicle", cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="vehicle", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="vehicle", cascade="all, delete-orphan")
    notes = relationship("VehicleNote", back_populates="vehicle", cascade="all, delete-orphan")
    rentals = relationship("VehicleRental", back_populates="vehicle", cascade="all, delete-orphan",
                           order_by="VehicleRental.date_from.desc()")

    @property
    def display_name(self):
        name = f"{self.brand} {self.model}"
        return f"{name} ({self.license_plate})" if self.license_plate else name

    @property
    def is_sold(self):
        return self.sale_date is not None and self.sale_date <= date.today()

    @property
    def last_rental(self):
        return max(self.rentals, key=lambda r: (r.date_from, r.id or 0)) if self.rentals else None

    @property
    def is_returned(self):
        """Půjčené vozidlo, jehož poslední půjčení už skončilo (vráceno)."""
        last = self.last_rental if self.is_rental else None
        return last is not None and last.date_to is not None and last.date_to <= date.today()

    @property
    def in_use(self):
        """Aktivní, neprodané a nevrácené vozidlo."""
        return bool(self.is_active) and not self.is_sold and not self.is_returned

    @property
    def is_moto(self):
        return self.kind == KIND_MOTO

    @property
    def kind_label(self):
        return VEHICLE_KINDS.get(self.kind or KIND_CAR, "")

    @property
    def tire_size_list(self):
        return [line.strip() for line in (self.tire_sizes or "").splitlines() if line.strip()]

    @property
    def owned_km(self):
        """Najeto za dobu vlastnictví (prodej - nákup), pokud známe oba stavy."""
        if self.purchase_odometer is None or self.sale_odometer is None:
            return None
        return self.sale_odometer - self.purchase_odometer

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
