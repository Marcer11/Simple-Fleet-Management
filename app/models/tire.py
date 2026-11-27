"""Pneumatiky: jednotlivé gumy / páry / sady, které lze nasazovat na různá vozidla."""
import re
from datetime import date

from sqlalchemy import Column, Integer, String, Date, Text, ForeignKey, DECIMAL, CHAR, Index
from sqlalchemy.orm import relationship

from .base import Base

TIRE_SEASONS = ["Letní", "Zimní", "Univerzální"]
# Pro jaký druh vozidla pneumatika je (stejné klíče jako Vehicle.kind)
TIRE_KINDS = {"car": "Auto", "moto": "Motorka"}
TIRE_RIMS = {"alu": "Alu disky", "steel": "Plechové disky", "": "Bez disků"}
TIRE_PLACES = {"service": "V servisu", "home": "Doma"}
# Vyřazení nasazených kol se zapisuje jako zvláštní „přezutí“ (sundání bez náhrady) - jen ze správy pneumatiky
SWAP_RETIRE = "retire"
SWAP_PLACE_LABELS = {**TIRE_PLACES, SWAP_RETIRE: "Vyřazení"}
# Typ pneumatik v textu (výběry, časová osa, hlášky) - stejně jako ikona místo slova
SEASON_SYMBOLS = {"Letní": "☀", "Zimní": "❄", "Univerzální": "☀❄"}
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
# Motorka: stejné pozice (náprava = kolo), jen jiné popisky; jednotlivá kola a rezerva nedávají smysl
MOTO_POSITIONS = {"all": "Obě kola", "front": "Přední kolo", "rear": "Zadní kolo"}
# Zkratka pozice v přehledu „Teď na vozidlech“ (všechna kola = bez zkratky)
POSITION_SHORT = {"all": "", "front": "P", "rear": "Z", "fl": "LP", "fr": "PP", "rl": "LZ", "rr": "PZ", "spare": "R"}
# Kola pro zápis dezénu: klíč, krátký a dlouhý popis
CAR_WHEELS = [("fl", "LP", "levé přední"), ("fr", "PP", "pravé přední"), ("rl", "LZ", "levé zadní"),
              ("rr", "PZ", "pravé zadní"), ("spare", "R", "rezerva")]
MOTO_WHEELS = [("f", "P", "přední"), ("r", "Z", "zadní")]
DAMAGE_POSITIONS = ["Levá přední", "Pravá přední", "Levá zadní", "Pravá zadní", "Přední", "Zadní", "Rezerva"]
# Zákonné minimum hloubky dezénu (mm): zimní a univerzální (v zimním období) 4 mm, letní 1,6 mm
LEGAL_MIN_TREAD = {"Zimní": 4.0, "Univerzální": 4.0, "Letní": 1.6}
# Motorka: 1,6 mm bez ohledu na typ (povinnost zimních pneumatik se na motorky nevztahuje)
LEGAL_MIN_TREAD_MOTO = 1.6
TIRE_RETIRED_REASONS = ["Prodej", "Poškození", "Opotřebení", "Jiné"]
TIRE_EXPENSE_CATEGORY = "Pneumatiky"
TIRE_SERVICE_TYPE = "Přezutí pneumatik"
TIRE_MAX_AGE_YEARS = 6  # starší pneumatiky tvrdnou - doporučená výměna


def position_label(position, kind=None):
    if kind == "moto" and position in MOTO_POSITIONS:
        return MOTO_POSITIONS[position]
    return TIRE_POSITIONS.get(position, (position or "", None))[0]


def positions_for(kind):
    """Pozice nabízené pro druh vozidla: {klíč: popisek}."""
    if kind == "moto":
        return dict(MOTO_POSITIONS)
    return {key: label for key, (label, _) in TIRE_POSITIONS.items()}


def tread_wheels(position, kind=None):
    """Kola, která pozice zabírá - pro zápis dezénu po kolech: [(klíč, zkratka, popis)]."""
    slots = position_slots(position)
    if kind == "moto":
        return [w for w in MOTO_WHEELS if (w[0] == "f" and "fl" in slots) or (w[0] == "r" and "rl" in slots)]
    return [w for w in CAR_WHEELS if w[0] in slots]


_SIZE_RE = re.compile(r"(\d{2,3})\s*/\s*(\d{2,3})\s*-?\s*Z?R?F?\s*(\d{2})", re.IGNORECASE)


def size_core(value):
    """Základ rozměru bez indexů: "225/45 ZR17 91W" -> "225/45R17" (pro porovnání s technickým průkazem)."""
    match = _SIZE_RE.search(value or "")
    return f"{match.group(1)}/{match.group(2)}R{match.group(3)}" if match else None


def size_fits(size, allowed):
    """True/False, zda rozměr pneumatiky odpovídá některému z povolených; None = nelze posoudit."""
    core = size_core(size)
    cores = {c for c in (size_core(a) for a in allowed or []) if c}
    if not core or not cores:
        return None
    return core in cores


def parse_treads(value):
    """"fl=5.5;fr=5.6" -> {"fl": "5.5", "fr": "5.6"}"""
    result = {}
    for part in (value or "").split(";"):
        key, _, mm = part.partition("=")
        if key.strip() and mm.strip():
            result[key.strip()] = mm.strip()
    return result


def format_treads(treads):
    return ";".join(f"{key}={value}" for key, value in treads.items() if value is not None) or None


def position_slots(position):
    return TIRE_POSITIONS[position][1] if position in TIRE_POSITIONS else frozenset()


def slots_positions(slots):
    """Obsazená místa -> co nejméně pozic: {fr, rl, rr} -> ["fr", "rear"]."""
    slots, result = set(slots), []
    exact = slots_position(frozenset(slots))
    if exact:
        return [exact]
    for key in ("front", "rear"):
        if TIRE_POSITIONS[key][1] <= slots:
            result.append(key)
            slots -= TIRE_POSITIONS[key][1]
    return result + [key for key in ("fl", "fr", "rl", "rr", "spare") if key in slots]


def slot_pieces(slots, kind=None):
    """Počet kusů na místech - u motorky je náprava jedno kolo."""
    if kind == "moto":
        return int(bool(slots & {"fl", "fr"})) + int(bool(slots & {"rl", "rr"}))
    return len(slots)


def slots_short(slots, kind=None):
    """Místa -> zkratka kol: {fl} -> "LP", motorka {fl, fr} -> "P"."""
    if kind == "moto":
        return " ".join(x for x, keys in (("P", {"fl", "fr"}), ("Z", {"rl", "rr"})) if slots & keys)
    return " ".join(short for key, short, _ in CAR_WHEELS if key in slots)


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
    kind = Column(String(10), nullable=False, default="car", server_default="car")  # car / moto
    manufacturer = Column(String(50), nullable=False)
    model = Column(String(50), nullable=True)
    size = Column(String(30), nullable=True)            # 205/55 R16 91H
    production_year = Column(Integer, nullable=True)    # z DOT
    dot = Column(String(10), nullable=True)             # např. 2322 (týden a rok)
    quantity = Column(Integer, nullable=False, default=2)
    rim = Column(String(10), nullable=False, default="")
    new_tread_mm = Column(DECIMAL(3, 1), nullable=True)  # hloubka dezénu při nákupu
    min_tread_mm = Column(DECIMAL(3, 1), nullable=True)  # vlastní minimum dezénu (prázdné = zákonné)
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
    tread_readings = relationship("TireTreadReading", back_populates="tire", cascade="all, delete-orphan")
    retirements = relationship("TireRetirement", back_populates="tire", cascade="all, delete-orphan",
                               order_by="TireRetirement.retire_date, TireRetirement.id")

    @property
    def name(self):
        """Výrobce a model bez typu (typ ukazuje ikona)."""
        return " ".join(x for x in (self.manufacturer, self.model) if x)

    @property
    def label(self):
        """Název do HTML vedle ikony typu - bez slova letní / zimní / univerzální."""
        return self.name

    @property
    def symbol(self):
        return SEASON_SYMBOLS.get(self.season, "")

    @property
    def text_label(self):
        """Název pro čistý text (výběry, časová osa, hlášky): značka typu místo slova - „❄ Nokian WR“."""
        return f"{self.symbol} {self.name}".strip()

    @property
    def retired_quantity(self):
        return sum(r.quantity for r in self.retirements)

    @property
    def active_quantity(self):
        """Kusy, které ještě nejsou vyřazené."""
        return max(self.quantity - self.retired_quantity, 0)

    @property
    def quantity_label(self):
        count = self.quantity if self.retired_date else self.active_quantity
        return {1: "1 ks", 2: "pár"}.get(count, f"{count} ks")

    @property
    def full_label(self):
        parts = [self.text_label, self.quantity_label]
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
    def is_moto(self):
        return self.kind == "moto"

    @property
    def kind_label(self):
        return TIRE_KINDS.get(self.kind or "car", "Auto")

    @property
    def legal_min_tread(self):
        if self.is_moto:
            return LEGAL_MIN_TREAD_MOTO
        return LEGAL_MIN_TREAD.get(self.season, 1.6)

    @property
    def min_tread(self):
        """Hlídané minimum dezénu: vlastní, jinak zákonné."""
        return float(self.min_tread_mm) if self.min_tread_mm is not None else self.legal_min_tread

    @property
    def open_mount(self):
        return next((m for m in self.mounts if m.removed_date is None), None)

    @property
    def open_mounts(self):
        return [m for m in self.mounts if m.removed_date is None]


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

    retirements = relationship("TireRetirement", back_populates="swap")

    @property
    def place_label(self):
        return SWAP_PLACE_LABELS.get(self.place, self.place)

    @property
    def is_retirement(self):
        return self.place == SWAP_RETIRE


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
    removed_tread_mm = Column(DECIMAL(3, 1), nullable=True)  # naměřeno při sundání (nejmenší z kol)
    removed_treads = Column(String(60), nullable=True)  # po kolech: "fl=5.5;fr=5.6;rl=6.5;rr=6.4"

    tire = relationship("Tire", back_populates="mounts")
    vehicle = relationship("Vehicle")
    swap = relationship("TireSwap", foreign_keys=[swap_id], back_populates="mounted")
    removed_swap = relationship("TireSwap", foreign_keys=[removed_swap_id], back_populates="removed")

    @property
    def kind(self):
        return self.vehicle.kind if self.vehicle is not None else None

    @property
    def position_label(self):
        return position_label(self.position, self.kind)

    @property
    def position_short(self):
        """Zkratka kol pro přehled: všechna = "", náprava P / Z, kolo LP, PP, LZ, PZ, rezerva R."""
        return POSITION_SHORT.get(self.position, "")

    @property
    def pieces(self):
        return slot_pieces(self.slots, self.kind)

    @property
    def slots(self):
        return position_slots(self.position)

    @property
    def wheels(self):
        return tread_wheels(self.position, self.kind)

    @property
    def tread_map(self):
        return parse_treads(self.removed_treads)

    @property
    def treads_label(self):
        """Dezén při sundání pro zobrazení: "LP 5,5 · PP 5,6 · LZ 6,5" nebo jen "5,5"."""
        values = self.tread_map
        if values:
            short = {w[0]: w[1] for w in CAR_WHEELS + MOTO_WHEELS}
            return " · ".join(f"{short.get(k, k)} {v.replace('.', ',')}" for k, v in values.items())
        if self.removed_tread_mm is not None:
            return f"{self.removed_tread_mm}".replace(".", ",")
        return ""


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


WHEEL_LABELS = {w[0]: (w[1], w[2]) for w in CAR_WHEELS + MOTO_WHEELS}


class TireTreadCheck(Base):
    """Průběžná kontrola hloubky dezénu na vozidle (každé kolo zvlášť)."""
    __tablename__ = "tire_tread_checks"
    __table_args__ = (Index("ix_tire_tread_checks_vehicle_date", "vehicle_id", "check_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    check_date = Column(Date, nullable=False)
    odometer = Column(Integer, nullable=False)
    note = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    vehicle = relationship("Vehicle")
    created_by = relationship("User")
    readings = relationship("TireTreadReading", back_populates="check", cascade="all, delete-orphan",
                            order_by="TireTreadReading.id")

    def by_tire(self):
        """[(pneumatika, [měření])] v pořadí kol."""
        order = [w[0] for w in CAR_WHEELS + MOTO_WHEELS]
        result = {}
        for r in sorted(self.readings, key=lambda r: order.index(r.wheel) if r.wheel in order else 99):
            result.setdefault(r.tire, []).append(r)
        return list(result.items())

    @property
    def summary(self):
        """"Letní Michelin: LP 6,0 · PP 6,1; Zimní Nokian: LZ 7,0"."""
        return "; ".join(f"{tire.text_label}: " + " · ".join(r.text for r in readings)
                         for tire, readings in self.by_tire())


class TireTreadReading(Base):
    """Naměřená hloubka dezénu jednoho kola při kontrole."""
    __tablename__ = "tire_tread_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    check_id = Column(Integer, ForeignKey("tire_tread_checks.id", ondelete="CASCADE"), nullable=False, index=True)
    tire_id = Column(Integer, ForeignKey("tires.id", ondelete="CASCADE"), nullable=False, index=True)
    mount_id = Column(Integer, ForeignKey("tire_mounts.id", ondelete="SET NULL"), nullable=True, index=True)
    wheel = Column(String(5), nullable=False)
    tread_mm = Column(DECIMAL(3, 1), nullable=False)

    check = relationship("TireTreadCheck", back_populates="readings")
    tire = relationship("Tire", back_populates="tread_readings")
    mount = relationship("TireMount")

    @property
    def wheel_short(self):
        return WHEEL_LABELS.get(self.wheel, (self.wheel, self.wheel))[0]

    @property
    def text(self):
        return f"{self.wheel_short} {self.tread_mm}".replace(".", ",")


class TireRetirement(Base):
    """Vyřazení části sady (jedno kolo, přední…) nebo všech zbývajících kusů. Vyřazení nasazených kol
    je zároveň „přezutí“ s místem SWAP_RETIRE, které je sundá z vozidla (swap)."""
    __tablename__ = "tire_retirements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tire_id = Column(Integer, ForeignKey("tires.id", ondelete="CASCADE"), nullable=False, index=True)
    retire_date = Column(Date, nullable=False)
    quantity = Column(Integer, nullable=False)
    wheels = Column(String(30), nullable=True)  # místa sundaná z vozidla: "fl" / "fl,fr"
    reason = Column(String(200), nullable=True)
    swap_id = Column(Integer, ForeignKey("tire_swaps.id", ondelete="SET NULL"), nullable=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    odometer = Column(Integer, nullable=True)

    tire = relationship("Tire", back_populates="retirements")
    swap = relationship("TireSwap", back_populates="retirements")
    vehicle = relationship("Vehicle")

    @property
    def slots(self):
        return frozenset(x for x in (self.wheels or "").split(",") if x)

    @property
    def wheels_label(self):
        """Zkratka vyřazených kol (LP, P…); kusy ze skladu se nepopisují."""
        kind = self.vehicle.kind if self.vehicle is not None else self.tire.kind
        return slots_short(self.slots, kind)

    @property
    def quantity_label(self):
        return f"{self.quantity} ks"
