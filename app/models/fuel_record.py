import re

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, DECIMAL, Text, CHAR, Index
from sqlalchemy.orm import relationship
from .base import Base


FUEL_TYPES = ["Benzín", "Nafta", "LPG", "CNG", "Elektřina"]
PAYMENT_METHODS = ["Karta", "Hotovost", "Tankovací karta", "Aplikace", "Firemní"]


# Druh paliva (kategorie) určuje jednotku a řadu pro výpočet spotřeby - konkrétní palivo
# (Natural 95, Verva Diesel…) si uživatel pojmenuje sám, viz FuelType
FUEL_CATEGORIES = FUEL_TYPES
_CATEGORY_RULES = (
    ("Elektřina", re.compile(r"elektř|elektr|\bkwh\b|\bev\b|nabíj")),
    ("CNG", re.compile(r"\bcng\b|zemní plyn")),
    ("LPG", re.compile(r"\blpg\b|autoplyn")),
    ("Nafta", re.compile(r"naft|diesel|dízl|\bd\b")),
    ("Benzín", re.compile(r"benz[ií]n|natural|\bba\s?\d|super|\be5\b|\be10\b|\b9[58]\b|\b10[02]\b|petrol")),
)


def guess_fuel_category(name):
    """Odhad druhu paliva podle názvu (Natural 95 -> Benzín, Verva Diesel -> Nafta), jinak None."""
    text = (name or "").strip().lower()
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(text):
            return category
    return None


def fuel_unit(fuel_type):
    """Jednotka množství paliva (kWh pro elektřinu, kg pro CNG, jinak litry)."""
    ft = (fuel_type or "").strip().lower()
    if ft.startswith("elektř") or ft.startswith("elektr"):
        return "kWh"
    if ft == "cng":
        return "kg"
    return "l"


class FuelRecord(Base):
    __tablename__ = 'fuel_records'
    # Názvy indexů odpovídají původnímu database.sql
    __table_args__ = (
        Index("idx_fuel_records_vehicle_id", "vehicle_id"),
        Index("idx_fuel_records_refuel_daterite", "refuel_datetime"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey('vehicles.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    refuel_datetime = Column(DateTime, nullable=False)
    odometer = Column(Integer, nullable=False)
    fuel_type = Column(String(30), nullable=False)
    # Druh paliva (Benzín, Nafta…) - řada pro spotřebu a jednotka; None = podle názvu paliva
    fuel_category = Column(String(15), nullable=True)
    volume_liters = Column(DECIMAL(7, 2), nullable=False)
    unit_price = Column(DECIMAL(10, 3), nullable=True)
    price_paid = Column(DECIMAL(12, 3), nullable=False)
    currency_code = Column(CHAR(3), nullable=False, default='CZK')
    unit_price_local = Column(DECIMAL(10, 3), nullable=True)
    price_local = Column(DECIMAL(12, 3), nullable=True)
    payment_method = Column(String(20), nullable=True)
    station_name = Column(String(100), nullable=True)
    station_address = Column(String(200), nullable=True)
    full_tank = Column(Boolean, nullable=False, default=False)
    skipped_refuel = Column(Boolean, nullable=False, default=False)
    consumption = Column(DECIMAL(5, 2), nullable=True)
    note = Column(Text, nullable=True)
    # Kdo tankování zapsal (u sdílených vozidel) - uživatel může být mezitím smazán
    created_by_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)

    # Napojení na tabulku vozidel
    vehicle = relationship('Vehicle', back_populates='fuel_records')
    created_by = relationship('User')

    @property
    def fuel_group(self):
        """Řada pro spotřebu: druh paliva, u neznámého paliva jeho název."""
        return self.fuel_category or (self.fuel_type or "").strip()

    @property
    def unit(self):
        return fuel_unit(self.fuel_group)

    def __repr__(self):
        return f"FuelRecord id={self.id} vehicle_id={self.vehicle_id} datetime={self.refuel_datetime}"
