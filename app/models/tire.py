from datetime import date

from sqlalchemy import Column, Integer, String, Date, Text, ForeignKey, DECIMAL, Index
from sqlalchemy.orm import relationship

from .base import Base

TIRE_SEASONS = ["Letní", "Zimní", "Univerzální"]
TIRE_RIMS = {"alu": "Alu disky", "steel": "Plechové disky", "": "Bez disků"}
TIRE_PLACES = {"service": "V servisu", "home": "Doma"}
TIRE_POSITIONS = ["Levá přední", "Pravá přední", "Levá zadní", "Pravá zadní", "Přední", "Zadní", "Rezerva",
                  "Celá sada"]
# Zákonné minimum hloubky dezénu (mm): zimní a univerzální (v zimním období) 4 mm, letní 1,6 mm
LEGAL_MIN_TREAD = {"Zimní": 4.0, "Univerzální": 4.0, "Letní": 1.6}
TIRE_EXPENSE_CATEGORY = "Pneumatiky"
TIRE_SERVICE_TYPE = "Přezutí pneumatik"
TIRE_MAX_AGE_YEARS = 6  # starší pneumatiky tvrdnou - doporučená výměna


class TireSet(Base):
    """Sada pneumatik vozidla (např. zimní Nokian na alu discích)."""
    __tablename__ = "tire_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    season = Column(String(15), nullable=False)
    manufacturer = Column(String(50), nullable=False)
    model = Column(String(50), nullable=True)
    size = Column(String(30), nullable=True)            # 205/55 R16 91H
    production_year = Column(Integer, nullable=True)    # z DOT
    dot = Column(String(10), nullable=True)             # např. 2322 (týden a rok)
    quantity = Column(Integer, nullable=False, default=4)
    rim = Column(String(10), nullable=False, default="")
    new_tread_mm = Column(DECIMAL(3, 1), nullable=True)  # hloubka dezénu při nákupu
    purchase_date = Column(Date, nullable=True)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)
    storage_location = Column(String(100), nullable=True)
    retired_date = Column(Date, nullable=True)
    retired_reason = Column(String(200), nullable=True)
    note = Column(Text, nullable=True)

    vehicle = relationship("Vehicle")
    expense = relationship("Expense")
    changes = relationship("TireChange", back_populates="tire_set", cascade="all, delete-orphan")
    damages = relationship("TireDamage", back_populates="tire_set", cascade="all, delete-orphan")

    @property
    def label(self):
        name = " ".join(x for x in (self.manufacturer, self.model) if x)
        return f"{self.season} {name}"

    @property
    def full_label(self):
        parts = [self.label]
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


class TireChange(Base):
    """Přezutí - nasazení sady (předchozí nasazená sada se tím sundá)."""
    __tablename__ = "tire_changes"
    __table_args__ = (Index("ix_tire_changes_vehicle_date", "vehicle_id", "change_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    change_date = Column(Date, nullable=False)
    odometer = Column(Integer, nullable=False)
    tire_set_id = Column(Integer, ForeignKey("tire_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    place = Column(String(10), nullable=False, default="home")
    service_record_id = Column(Integer, ForeignKey("service_records.id", ondelete="SET NULL"), nullable=True)
    removed_tread_mm = Column(DECIMAL(3, 1), nullable=True)  # naměřeno na sundané sadě
    note = Column(Text, nullable=True)

    vehicle = relationship("Vehicle")
    tire_set = relationship("TireSet", back_populates="changes")
    service_record = relationship("ServiceRecord")

    @property
    def place_label(self):
        return TIRE_PLACES.get(self.place, self.place)


class TireDamage(Base):
    """Poškození pneumatiky (defekt, boule, řez…) s volitelnou cenou opravy."""
    __tablename__ = "tire_damages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    tire_set_id = Column(Integer, ForeignKey("tire_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    damage_date = Column(Date, nullable=False)
    odometer = Column(Integer, nullable=True)
    position = Column(String(20), nullable=True)
    description = Column(String(200), nullable=False)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)

    vehicle = relationship("Vehicle")
    tire_set = relationship("TireSet", back_populates="damages")
    expense = relationship("Expense")
