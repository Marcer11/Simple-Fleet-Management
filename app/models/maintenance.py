from sqlalchemy import Column, Integer, String, Boolean, Date, ForeignKey, DECIMAL, Text, CHAR
from sqlalchemy.orm import relationship
from .base import Base


SERVICE_TYPES = [
    "Výměna oleje", "Brzdy", "Rozvody", "Filtry", "Pneumatiky", "STK", "Emise",
    "Klimatizace", "Baterie", "Karoserie", "Pravidelná prohlídka", "Oprava", "Ostatní",
]

SERVICE_TYPE_SEPARATOR = ", "


def split_service_types(value):
    """"Výměna oleje, Brzdy" -> ["Výměna oleje", "Brzdy"] (bez prázdných a duplicit)."""
    result = []
    for part in (value or "").split(","):
        part = part.strip()
        if part and part.lower() not in (x.lower() for x in result):
            result.append(part)
    return result


def join_service_types(types):
    return SERVICE_TYPE_SEPARATOR.join(split_service_types(",".join(t for t in types if t)))


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

# Výdaje s omezenou platností - formulář u nich nabídne platnost a upomínku
VIGNETTE_CATEGORY = "Dálniční známka"
VALIDITY_CATEGORIES = [VIGNETTE_CATEGORY, "Pojištění", "Parkování", "Daň"]

# Česká elektronická dálniční známka: (popis, počet dní platnosti včetně prvního dne)
VIGNETTE_VARIANTS = {
    "year": ("Roční (365 dní)", 365),
    "30d": ("30denní", 30),
    "10d": ("10denní", 10),
    "1d": ("Jednodenní", 1),
}


class InsuranceMixin:
    """Pojistné plnění: náklad (servis po nehodě, výdaj) zcela nebo zčásti uhradila pojišťovna."""
    insurance_claim = Column(Boolean, nullable=False, default=False, server_default="0")
    insurer = Column(String(100), nullable=True)            # pojišťovna
    policy_number = Column(String(50), nullable=True)       # číslo pojistky
    claim_number = Column(String(50), nullable=True)        # číslo pojistné události
    insurance_paid = Column(DECIMAL(12, 3), nullable=True)  # Kč uhrazené pojišťovnou

    @property
    def own_cost(self):
        """Náklad, který zůstal na majiteli (cena v Kč minus plnění pojišťovny)."""
        if self.price_local is None:
            return None
        if self.insurance_claim and self.insurance_paid is not None:
            return max(self.price_local - self.insurance_paid, 0)
        return self.price_local


class ServiceRecord(InsuranceMixin, Base):
    """Záznam o provedeném servisu."""
    __tablename__ = "service_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    service_date = Column(Date, nullable=False)
    odometer = Column(Integer, nullable=True)
    service_type = Column(String(255), nullable=False)  # jedna nebo více položek oddělených ", "
    place = Column(String(100), nullable=True)
    price_paid = Column(DECIMAL(12, 3), nullable=True)
    currency_code = Column(CHAR(3), nullable=False, default="CZK")
    price_local = Column(DECIMAL(12, 3), nullable=True)
    note = Column(Text, nullable=True)

    vehicle = relationship("Vehicle", back_populates="service_records")

    @property
    def types(self):
        return split_service_types(self.service_type)


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

    is_default = False  # univerzální interval je services.maintenance_service.EffectiveInterval


class VehicleRental(Base):
    """Půjčení vozidla (půjčovna nebo od koho, období, kilometry, půjčovné) - u jednoho vozidla opakovaně."""
    __tablename__ = "vehicle_rentals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(100), nullable=False)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=True)
    odometer_from = Column(Integer, nullable=True)
    odometer_to = Column(Integer, nullable=True)
    price_paid = Column(DECIMAL(12, 3), nullable=True)
    currency_code = Column(CHAR(3), nullable=False, default="CZK")
    price_local = Column(DECIMAL(12, 3), nullable=True)
    note = Column(Text, nullable=True)

    vehicle = relationship("Vehicle", back_populates="rentals")

    @property
    def distance(self):
        """Najeto během půjčení (jen když známe oba stavy; 0 je platný stav)."""
        if self.odometer_from is None or self.odometer_to is None:
            return None
        return self.odometer_to - self.odometer_from

    @property
    def days(self):
        return (self.date_to - self.date_from).days + 1 if self.date_to else None


class DefaultServiceInterval(Base):
    """Univerzální interval uživatele - platí pro jeho vozidla, pokud u vozidla není nastaven jinak."""
    __tablename__ = "default_service_intervals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    service_type = Column(String(50), nullable=False)
    vehicle_kind = Column(String(10), nullable=True)  # None = všechna vozidla, jinak "car" / "moto"
    interval_months = Column(Integer, nullable=True)
    interval_km = Column(Integer, nullable=True)

    def applies_to(self, vehicle):
        return self.vehicle_kind in (None, "", vehicle.kind or "car")


# Doporučené univerzální intervaly (nabídnou se, dokud uživatel žádné nemá)
SUGGESTED_INTERVALS = [
    ("Výměna oleje", None, 12, 15000),
    ("Filtry", None, 24, 30000),
    ("Brzdová kapalina", None, 24, None),
    ("Rozvody", "car", 60, 120000),
    ("STK", None, 24, None),
    ("Klimatizace", "car", 24, None),
]


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


class Expense(InsuranceMixin, Base):
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
    # Platnost (dálniční známka, pojištění, ...) a automaticky vytvořená upomínka konce platnosti
    valid_from = Column(Date, nullable=True)
    valid_until = Column(Date, nullable=True)
    reminder_id = Column(Integer, ForeignKey("reminders.id", ondelete="SET NULL", name="fk_expenses_reminder"),
                         nullable=True, index=True)

    vehicle = relationship("Vehicle", back_populates="expenses")
    reminder = relationship("Reminder")
