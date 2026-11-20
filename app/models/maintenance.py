from sqlalchemy import Column, Integer, String, Boolean, Date, ForeignKey, DECIMAL, Text, CHAR
from sqlalchemy.orm import relationship
from .base import Base


SERVICE_TYPES = [
    "Výměna oleje", "Brzdy", "Rozvody", "Filtry", "Pneumatiky", "STK", "Emise",
    "Klimatizace", "Baterie", "Karoserie", "Pravidelná prohlídka", "Oprava", "Ostatní",
]

REPEAT_NONE = "none"
REPEAT_OPTIONS = {
    REPEAT_NONE: "Jednorázově",
    "daily": "Denně",
    "weekly": "Týdně",
    "monthly": "Měsíčně",
    "yearly": "Ročně",
}

EXPENSE_CATEGORIES = [
    "Dálniční známka", "Pojištění", "Provozní kapaliny", "Mytí", "Parkování", "Mýtné",
    "Pneumatiky", "Příslušenství", "Daň", "Pokuta", "Ostatní",
]


class ServiceRecord(Base):
    """Záznam o provedeném servisu."""
    __tablename__ = "service_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    service_date = Column(Date, nullable=False)
    odometer = Column(Integer, nullable=True)
    service_type = Column(String(50), nullable=False)
    place = Column(String(100), nullable=True)
    price_paid = Column(DECIMAL(12, 3), nullable=True)
    currency_code = Column(CHAR(3), nullable=False, default="CZK")
    price_local = Column(DECIMAL(12, 3), nullable=True)
    note = Column(Text, nullable=True)

    vehicle = relationship("Vehicle", back_populates="service_records")


class ServiceInterval(Base):
    """Pravidelný servis - časový a/nebo kilometrový interval."""
    __tablename__ = "service_intervals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    service_type = Column(String(50), nullable=False)
    interval_months = Column(Integer, nullable=True)
    interval_km = Column(Integer, nullable=True)
    # Výchozí bod, pokud ještě neexistuje žádný servisní záznam daného typu
    start_date = Column(Date, nullable=True)
    start_odometer = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    vehicle = relationship("Vehicle", back_populates="service_intervals")


class Reminder(Base):
    """Jednorázová nebo opakovaná upomínka (datum a/nebo stav tachometru)."""
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(100), nullable=False)
    note = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    due_odometer = Column(Integer, nullable=True)
    repeat = Column(String(10), nullable=False, default=REPEAT_NONE)
    repeat_km = Column(Integer, nullable=True)
    notify_days_before = Column(Integer, nullable=False, default=14)
    notify_km_before = Column(Integer, nullable=False, default=500)
    is_done = Column(Boolean, nullable=False, default=False)

    vehicle = relationship("Vehicle", back_populates="reminders")


class Expense(Base):
    """Ostatní výdaje (dálniční známka, pojištění, mytí, ...)."""
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    expense_date = Column(Date, nullable=False)
    category = Column(String(30), nullable=False)
    description = Column(String(200), nullable=True)
    odometer = Column(Integer, nullable=True)
    price_paid = Column(DECIMAL(12, 3), nullable=False)
    currency_code = Column(CHAR(3), nullable=False, default="CZK")
    price_local = Column(DECIMAL(12, 3), nullable=True)
    note = Column(Text, nullable=True)

    vehicle = relationship("Vehicle", back_populates="expenses")
