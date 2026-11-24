"""Pneumatiky: jednotlivé gumy / páry / sady, které lze nasazovat na různá vozidla."""
from datetime import date

from sqlalchemy import Column, Integer, String, Date, Text, ForeignKey, DECIMAL, CHAR, Index
from sqlalchemy.orm import relationship

from .base import Base

TIRE_SEASONS = ["Letní", "Zimní", "Univerzální"]
TIRE_RIMS = {"alu": "Alu disky", "steel": "Plechové disky", "": "Bez disků"}
TIRE_PLACES = {"service": "V servisu", "home": "Doma"}
# Pozice na vozidle -> (popisek, obsazená místa); u motorky stačí přední / zadní
TIRE_POSITIONS = {
    "all": ("Všechna kola", frozenset({"fl", "fr", "rl", "rr"})),
    "front": ("Přední náprava", frozenset({"fl", "fr"})),
    "rear": ("Zadní náprava", frozenset({"rl", "rr"})),
    "fl": ("Levé přední", frozenset({"fl"})),
    "fr": ("Pravé přední", frozenset({"fr"})),
    "rl": ("Levé zadní", frozenset({"rl"})),
    "rr": ("Pravé zadní", frozenset({"rr"})),
    "spare": ("Rezerva", frozenset({"spare"})),
}
DAMAGE_POSITIONS = ["Levá přední", "Pravá přední", "Levá zadní", "Pravá zadní", "Přední", "Zadní", "Rezerva"]
# Zákonné minimum hloubky dezénu (mm): zimní a univerzální (v zimním období) 4 mm, letní 1,6 mm
LEGAL_MIN_TREAD = {"Zimní": 4.0, "Univerzální": 4.0, "Letní": 1.6}
TIRE_EXPENSE_CATEGORY = "Pneumatiky"
TIRE_SERVICE_TYPE = "Přezutí pneumatik"
TIRE_MAX_AGE_YEARS = 6  # starší pneumatiky tvrdnou - doporučená výměna


def position_label(position):
    return TIRE_POSITIONS.get(position, (position or "", None))[0]


def position_slots(position):
    return TIRE_POSITIONS[position][1] if position in TIRE_POSITIONS else frozenset()


def slots_position(slots):
    """Obsazená místa -> pozice (např. {rl, rr} -> "rear"), jinak None."""
    for key, (_, key_slots) in TIRE_POSITIONS.items():
        if key_slots == slots:
            return key
    return None


class Tire(Base):
    """Pneumatika - jedna guma, pár nebo sada (quantity). Patří uživateli, ne vozidlu."""
    __tablename__ = "tires"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    season = Column(String(15), nullable=False)
    manufacturer = Column(String(50), nullable=False)
    model = Column(String(50), nullable=True)
    size = Column(String(30), nullable=True)            # 205/55 R16 91H
    production_year = Column(Integer, nullable=True)    # z DOT
    dot = Column(String(10), nullable=True)             # např. 2322 (týden a rok)
    quantity = Column(Integer, nullable=False, default=2)
    rim = Column(String(10), nullable=False, default="")
    new_tread_mm = Column(DECIMAL(3, 1), nullable=True)  # hloubka dezénu při nákupu
    purchase_date = Column(Date, nullable=True)
    price_paid = Column(DECIMAL(12, 3), nullable=True)
    currency_code = Column(CHAR(3), nullable=False, default="CZK")
    price_local = Column(DECIMAL(12, 3), nullable=True)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)
    storage_location = Column(String(100), nullable=True)
    retired_date = Column(Date, nullable=True)
    retired_reason = Column(String(200), nullable=True)
    note = Column(Text, nullable=True)

    owner = relationship("User")
    expense = relationship("Expense")
    mounts = relationship("TireMount", back_populates="tire", cascade="all, delete-orphan",
                          order_by="TireMount.mounted_date, TireMount.id")
    defects = relationship("TireDefect", back_populates="tire", cascade="all, delete-orphan")

    @property
    def label(self):
        name = " ".join(x for x in (self.manufacturer, self.model) if x)
        return f"{self.season} {name}"

    @property
    def quantity_label(self):
        return {1: "1 ks", 2: "pár"}.get(self.quantity, f"{self.quantity} ks")

    @property
    def full_label(self):
        parts = [self.label, self.quantity_label]
        if self.size:
            parts.append(self.size)
        if self.rim:
            parts.append(TIRE_RIMS.get(self.rim, self.rim).lower())
        return ", ".join(parts)

    @property
    def rim_label(self):
        return TIRE_RIMS.get(self.rim or "", "")

    @property
    def age_years(self):
        year = self.production_year or (self.purchase_date.year if self.purchase_date else None)
        return (date.today().year - year) if year else None

    @property
    def legal_min_tread(self):
        return LEGAL_MIN_TREAD.get(self.season, 1.6)

    @property
    def open_mount(self):
        return next((m for m in self.mounts if m.removed_date is None), None)


class TireSwap(Base):
    """Přezutí - událost na vozidle (doma nebo v servisu), při které se pneumatiky nasazují / sundávají."""
    __tablename__ = "tire_swaps"
    __table_args__ = (Index("ix_tire_swaps_vehicle_date", "vehicle_id", "swap_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    swap_date = Column(Date, nullable=False)
    odometer = Column(Integer, nullable=False)
    place = Column(String(10), nullable=False, default="home")
    service_record_id = Column(Integer, ForeignKey("service_records.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=True)

    vehicle = relationship("Vehicle")
    service_record = relationship("ServiceRecord")
    mounted = relationship("TireMount", foreign_keys="TireMount.swap_id", back_populates="swap",
                           cascade="all, delete-orphan")
    removed = relationship("TireMount", foreign_keys="TireMount.removed_swap_id", back_populates="removed_swap")

    @property
    def place_label(self):
        return TIRE_PLACES.get(self.place, self.place)


class TireMount(Base):
    """Období, kdy byla pneumatika nasazená na vozidle na dané pozici."""
    __tablename__ = "tire_mounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tire_id = Column(Integer, ForeignKey("tires.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(String(10), nullable=False, default="all")
    swap_id = Column(Integer, ForeignKey("tire_swaps.id", ondelete="CASCADE"), nullable=False, index=True)
    mounted_date = Column(Date, nullable=False)
    mounted_km = Column(Integer, nullable=False)
    removed_swap_id = Column(Integer, ForeignKey("tire_swaps.id", ondelete="SET NULL"), nullable=True, index=True)
    removed_date = Column(Date, nullable=True)
    removed_km = Column(Integer, nullable=True)
    removed_tread_mm = Column(DECIMAL(3, 1), nullable=True)  # naměřeno při sundání

    tire = relationship("Tire", back_populates="mounts")
    vehicle = relationship("Vehicle")
    swap = relationship("TireSwap", foreign_keys=[swap_id], back_populates="mounted")
    removed_swap = relationship("TireSwap", foreign_keys=[removed_swap_id], back_populates="removed")

    @property
    def position_label(self):
        return position_label(self.position)

    @property
    def slots(self):
        return position_slots(self.position)


class TireDefect(Base):
    """Poškození pneumatiky (defekt, boule, řez…) s volitelnou cenou opravy."""
    __tablename__ = "tire_defects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tire_id = Column(Integer, ForeignKey("tires.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True)
    defect_date = Column(Date, nullable=False)
    odometer = Column(Integer, nullable=True)
    position = Column(String(20), nullable=True)
    description = Column(String(200), nullable=False)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)

    tire = relationship("Tire", back_populates="defects")
    vehicle = relationship("Vehicle")
    expense = relationship("Expense")
