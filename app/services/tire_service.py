"""Pneumatiky: evidence gum / párů / sad, přezutí na vozidla a pozice, poškození, životnost, upozornění.

Pneumatika patří uživateli a během života může být na různých vozidlech. Každé nasazení
(TireMount) je období na konkrétním vozidle a pozici; přezutí (TireSwap) nasazení otevírá
a zavírá. Nasazením na obsazenou pozici se původní pneumatika sundá - když se mění jen přední,
zůstane zbytek sady na zadní nápravě.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import joinedload

from models import Tire, TireDefect, TireMount, TireSwap, TireTreadCheck, TireTreadReading
from models.tire import (
    TIRE_EXPENSE_CATEGORY, TIRE_MAX_AGE_YEARS, TIRE_PLACES, TIRE_POSITIONS, TIRE_RIMS, TIRE_SEASONS, TIRE_KINDS,
    TIRE_SERVICE_TYPE, CAR_WHEELS, MOTO_POSITIONS, MOTO_WHEELS, format_treads, slots_position,
)
from services.errors import NotFoundError, ValidationError
from services.maintenance_service import (
    DueStatus, ExpenseService, ServiceRecordService, LEVEL_OVERDUE, LEVEL_WARNING,
    _clean_str, _positive_int, check_odometer_order,
)
from services.pricing import convert_price, to_decimal

TREAD_MAX = Decimal("20")


def _tread(value, label="Hloubka dezénu"):
    value = to_decimal(value, Decimal("0.1"))
    if value is not None and not (0 <= value <= TREAD_MAX):
        raise ValidationError(f"{label} musí být 0–20 mm.")
    return value


def _apply_treads(mount, values):
    """Dezén při sundání: values = {kolo: mm} (po kolech) nebo {"": mm} (jedna hodnota pro všechna kola).
    Do removed_tread_mm se ukládá nejmenší naměřená hodnota - podle ní se hlídá zákonné minimum."""
    values = values or {}
    keys = [w[0] for w in mount.wheels]
    per_wheel = {k: _tread(values[k]) for k in keys if values.get(k) not in (None, "")}
    per_wheel = {k: v for k, v in per_wheel.items() if v is not None}
    if per_wheel:
        mount.removed_treads = format_treads({k: str(v) for k, v in per_wheel.items()})
        mount.removed_tread_mm = min(per_wheel.values())
    else:
        mount.removed_treads = None
        mount.removed_tread_mm = _tread(values.get(""))


def mounted_seasons(session, vehicle_ids):
    """Co je teď na vozidlech (bez rezervy): {vehicle_id: [(typ, [popisky pneumatik])]}."""
    if not vehicle_ids:
        return {}
    mounts = (session.query(TireMount).options(joinedload(TireMount.tire))
              .filter(TireMount.vehicle_id.in_(vehicle_ids), TireMount.removed_date.is_(None),
                      TireMount.position != "spare").all())
    result = {}
    for m in sorted(mounts, key=lambda m: (list(TIRE_POSITIONS).index(m.position)
                                           if m.position in TIRE_POSITIONS else 99, m.id)):
        seasons = result.setdefault(m.vehicle_id, {})
        seasons.setdefault(m.tire.season, []).append(f"{m.tire.label} ({m.position_label.lower()})")
    return {vid: list(seasons.items()) for vid, seasons in result.items()}


def _has_price(price):
    return bool(price) and price.get("price_paid") not in (None, "")


def _sync_expense(session, owner, price, vehicle_id, expense_date, description, odometer=None):
    """Výdaj navázaný na pneumatiku / poškození: založí, upraví, nebo (bez ceny či vozidla) smaže."""
    expenses = ExpenseService(session)
    if not _has_price(price) or not vehicle_id:
        if owner.expense is not None:
            expense = owner.expense
            owner.expense = None
            expenses.delete(expense)
        return
    data = {"vehicle_id": vehicle_id, "expense_date": expense_date, "category": TIRE_EXPENSE_CATEGORY,
            "description": description[:200], "odometer": odometer, **price}
    if owner.expense is not None:
        expenses.update(owner.expense, data)
    else:
        owner.expense = expenses.create(**data)
        session.commit()


# ----------------------------------------------------------------------
# Pneumatiky
# ----------------------------------------------------------------------

class TireService:
    def __init__(self, session):
        self.session = session

    def list_for_user(self, user, include_retired=True):
        query = (self.session.query(Tire).options(joinedload(Tire.mounts), joinedload(Tire.expense))
                 .filter(Tire.owner_id == user.id))
        if not include_retired:
            query = query.filter(Tire.retired_date.is_(None))
        return sorted(query.all(), key=lambda t: (t.retired_date is not None, t.season, t.manufacturer, t.id))

    def get_for_user(self, user, tire_id):
        tire = self.session.get(Tire, tire_id) if tire_id else None
        if tire is None or tire.owner_id != user.id:
            raise NotFoundError("Pneumatika nenalezena.")
        return tire

    def create(self, user, data):
        price, expense_vehicle_id = data.pop("price", None), data.pop("expense_vehicle_id", None)
        tire = Tire(owner_id=user.id, **self._validate(data, price))
        self.session.add(tire)
        self.session.commit()
        self._sync(tire, price, expense_vehicle_id)
        return tire

    def update(self, tire, data):
        price, expense_vehicle_id = data.pop("price", None), data.pop("expense_vehicle_id", None)
        values = self._validate(data, price)
        mount = tire.open_mount
        if mount and mount.vehicle and values["kind"] != (mount.vehicle.kind or "car"):
            raise ValidationError(f"Pneumatika je nasazená na {'motorce' if mount.vehicle.kind == 'moto' else 'autě'} "
                                  f"{mount.vehicle.short_name} – nejdřív ji sundejte.")
        for key, value in values.items():
            setattr(tire, key, value)
        self.session.commit()
        self._sync(tire, price, expense_vehicle_id)
        return tire

    def _sync(self, tire, price, vehicle_id):
        _sync_expense(self.session, tire, price, vehicle_id, tire.purchase_date or date.today(),
                      f"Nákup pneumatik: {tire.full_label}")

    def delete(self, tire):
        """Smaže pneumatiku i s nasazeními a poškozeními, výdaji za nákup a opravy a přezutími,
        ve kterých nic jiného nezůstalo."""
        linked = [tire.expense] + [d.expense for d in tire.defects]
        swaps = {m.swap for m in tire.mounts}
        checks = {r.check for r in tire.tread_readings}
        self.session.delete(tire)
        self.session.flush()
        for check in checks:
            self.session.refresh(check)
            if not check.readings:
                self.session.delete(check)
        for swap in swaps:
            self.session.refresh(swap)
            if not swap.mounted:
                linked.append(swap.service_record)
                self.session.delete(swap)
        for item in linked:
            if item is not None:
                self.session.delete(item)
        self.session.commit()

    def _validate(self, data, price):
        season = data.get("season")
        if season not in TIRE_SEASONS:
            raise ValidationError("Vyberte typ pneumatik (letní, zimní, univerzální).")
        kind = data.get("kind") or "car"
        if kind not in TIRE_KINDS:
            raise ValidationError("Vyberte, zda jsou pneumatiky pro auto, nebo motorku.")
        rim = data.get("rim") or ""
        if rim not in TIRE_RIMS:
            raise ValidationError("Neplatný typ disků.")
        year = data.get("production_year")
        if year not in (None, "") and not (1990 <= int(year) <= date.today().year + 1):
            raise ValidationError("Neplatný rok výroby pneumatik.")
        quantity = _positive_int(data.get("quantity"), "Počet kusů") or 2
        if not 1 <= quantity <= 8:
            raise ValidationError("Počet kusů musí být 1–8.")
        retired = data.get("retired_date")
        if retired and data.get("purchase_date") and retired < data["purchase_date"]:
            raise ValidationError("Vyřazení nemůže být před nákupem.")
        new_tread = _tread(data.get("new_tread_mm"))
        min_tread = _tread(data.get("min_tread_mm"), "Minimální dezén")
        if min_tread is not None and min_tread <= 0:
            raise ValidationError("Minimální dezén musí být větší než nula.")
        if min_tread is not None and new_tread is not None and min_tread >= new_tread:
            raise ValidationError("Minimální dezén musí být menší než dezén při nákupu.")
        currency, price_paid, price_local = "CZK", None, None
        if _has_price(price):
            currency, price_paid, price_local = convert_price(
                price["price_paid"], price.get("currency_code"), data.get("purchase_date") or date.today(),
                price.get("manual_rate"))
        return {
            "season": season,
            "kind": kind,
            "manufacturer": _clean_str(data.get("manufacturer"), 50, "Výrobce", required=True),
            "model": _clean_str(data.get("model"), 50, "Model"),
            "size": _clean_str(data.get("size"), 30, "Rozměr"),
            "production_year": int(year) if year not in (None, "") else None,
            "dot": _clean_str(data.get("dot"), 10, "DOT"),
            "quantity": quantity,
            "rim": rim,
            "new_tread_mm": new_tread,
            "min_tread_mm": min_tread,
            "purchase_date": data.get("purchase_date"),
            "price_paid": price_paid,
            "currency_code": currency,
            "price_local": price_local,
            "storage_location": _clean_str(data.get("storage_location"), 100, "Místo uložení"),
            "retired_date": retired,
            "retired_reason": _clean_str(data.get("retired_reason"), 200, "Důvod vyřazení") if retired else None,
            "note": _clean_str(data.get("note")),
        }


# ----------------------------------------------------------------------
# Přezutí
# ----------------------------------------------------------------------

def open_mounts(session, vehicle_id):
    """Pneumatiky právě nasazené na vozidle."""
    mounts = (session.query(TireMount).options(joinedload(TireMount.tire))
              .filter(TireMount.vehicle_id == vehicle_id, TireMount.removed_date.is_(None)).all())
    order = list(TIRE_POSITIONS)
    return sorted(mounts, key=lambda m: (order.index(m.position) if m.position in order else 99, m.id))


class TireSwapService:
    def __init__(self, session):
        self.session = session

    def get(self, swap_id):
        return self.session.get(TireSwap, swap_id)

    def for_vehicles(self, vehicle_ids, limit=None):
        if not vehicle_ids:
            return []
        query = (self.session.query(TireSwap).filter(TireSwap.vehicle_id.in_(vehicle_ids))
                 .order_by(TireSwap.swap_date.desc(), TireSwap.id.desc()))
        return query.limit(limit).all() if limit else query.all()

    def _check_common(self, vehicle_id, swap_date, odometer, place, exclude_id=None):
        if not swap_date:
            raise ValidationError("Datum přezutí je povinné.")
        if swap_date > date.today():
            raise ValidationError("Datum přezutí nemůže být v budoucnosti.")
        odometer = _positive_int(odometer, "Stav tachometru", allow_none=False)
        if place not in TIRE_PLACES:
            raise ValidationError("Neplatné místo přezutí.")
        check_odometer_order(self.session, vehicle_id, datetime.combine(swap_date, datetime.min.time()), odometer,
                             has_time=False, exclude=("tire_swap", exclude_id))
        return odometer

    def create(self, vehicle, swap_date, odometer, place="home", service_place=None, price=None, note=None,
               new_mounts=(), remove_ids=(), treads=None):
        """new_mounts = [(Tire, pozice)], remove_ids = id nasazení k sundání bez náhrady,
        treads = {id nasazení: {kolo: naměřený dezén při sundání}} (kolo "" = jedna hodnota pro celé nasazení)."""
        treads = treads or {}
        odometer = self._check_common(vehicle.id, swap_date, odometer, place)
        last = (self.session.query(TireSwap.swap_date).filter(TireSwap.vehicle_id == vehicle.id)
                .order_by(TireSwap.swap_date.desc()).first())
        if last and swap_date < last[0]:
            raise ValidationError(f"Na vozidle je novější přezutí ({last[0]:%d.%m.%Y}) – starší přezutí "
                                  "lze zapsat jen po smazání novějšího.")
        current = open_mounts(self.session, vehicle.id)
        remove_ids = {i for i in remove_ids if i in {m.id for m in current}}
        if not new_mounts and not remove_ids:
            raise ValidationError("Vyberte pneumatiky k nasazení nebo sundání.")
        new_slots, seen = set(), set()
        for tire, position in new_mounts:
            if position not in TIRE_POSITIONS:
                raise ValidationError("Vyberte pozici pneumatiky.")
            if vehicle.kind == "moto" and position not in MOTO_POSITIONS:
                raise ValidationError("Na motorce lze nasadit jen přední, zadní nebo obě kola.")
            if tire.id in seen:
                raise ValidationError(f"Pneumatika {tire.label} je vybraná dvakrát.")
            if tire.retired_date:
                raise ValidationError(f"Pneumatika {tire.label} je vyřazená.")
            if (tire.kind or "car") != (vehicle.kind or "car"):
                raise ValidationError(f"Pneumatika {tire.label} je pro {'motorku' if tire.is_moto else 'auto'} – "
                                      f"na {'motorku' if vehicle.kind == 'moto' else 'auto'} ji nelze nasadit.")
            slots = TIRE_POSITIONS[position][1]
            if slots & new_slots:
                raise ValidationError("Dvě pneumatiky nemohou být na stejné pozici.")
            last_mount = max((m.mounted_date for m in tire.mounts), default=None)
            if last_mount and last_mount > swap_date:
                raise ValidationError(f"Pneumatika {tire.label} byla nasazena až {last_mount:%d.%m.%Y}.")
            seen.add(tire.id)
            new_slots |= slots

        swap = TireSwap(vehicle_id=vehicle.id, swap_date=swap_date, odometer=odometer, place=place,
                        note=_clean_str(note))
        self.session.add(swap)
        self.session.flush()

        for mount in current:
            explicit = mount.id in remove_ids
            moving = mount.tire_id in seen
            overlap = mount.slots & new_slots
            if not (explicit or moving or overlap):
                continue
            self._close(mount, swap, odometer, treads.get(mount.id))
            rest = mount.slots - new_slots
            if overlap and rest and not explicit and not moving:
                # vyměněna jen část (např. přední) - zbytek zůstává na voze
                rest_position = slots_position(frozenset(rest))
                if rest_position:
                    self.session.add(TireMount(tire_id=mount.tire_id, vehicle_id=vehicle.id, position=rest_position,
                                               swap=swap, mounted_date=swap_date, mounted_km=odometer))

        from services.vehicle_service import VehicleService
        vehicles = VehicleService(self.session)
        for tire, position in new_mounts:
            for other in (self.session.query(TireMount)
                          .filter(TireMount.tire_id == tire.id, TireMount.removed_date.is_(None))):
                # pneumatika přechází z jiného vozidla - tam se sundá k aktuálnímu stavu tachometru
                km = vehicles.get_current_odometer(other.vehicle_id) or other.mounted_km
                self._close(other, swap, max(km, other.mounted_km), None)
            self.session.add(TireMount(tire_id=tire.id, vehicle_id=vehicle.id, position=position, swap=swap,
                                       mounted_date=swap_date, mounted_km=odometer))
        self.session.flush()
        self._sync_service(swap, price, service_place)
        self.session.commit()
        return swap

    @staticmethod
    def _close(mount, swap, km, treads):
        mount.removed_swap = swap
        mount.removed_date = swap.swap_date
        mount.removed_km = km
        _apply_treads(mount, treads)

    def update(self, swap, swap_date, odometer, place="home", service_place=None, price=None, note=None,
               treads=None):
        """Úprava data, km, místa a ceny; nasazené pneumatiky se nemění (na to je nové přezutí)."""
        odometer = self._check_common(swap.vehicle_id, swap_date, odometer, place, exclude_id=swap.id)
        for mount in swap.removed:
            if mount.mounted_date > swap_date or (mount.vehicle_id == swap.vehicle_id and mount.mounted_km > odometer):
                raise ValidationError("Přezutí nemůže být dřív než nasazení pneumatik, které se při něm sundaly.")
        for mount in swap.mounted:
            if mount.removed_date and mount.removed_date < swap_date:
                raise ValidationError("Přezutí nemůže být později než sundání pneumatik, které se při něm nasadily.")
        swap.swap_date, swap.odometer, swap.place, swap.note = swap_date, odometer, place, _clean_str(note)
        for mount in swap.mounted:
            mount.mounted_date, mount.mounted_km = swap_date, odometer
        for mount in swap.removed:
            mount.removed_date = swap_date
            if mount.vehicle_id == swap.vehicle_id:
                mount.removed_km = odometer
            if treads is not None and mount.id in treads:
                _apply_treads(mount, treads[mount.id])
        self.session.flush()
        self._sync_service(swap, price, service_place)
        self.session.commit()
        return swap

    @staticmethod
    def can_delete(swap):
        """Smazat lze jen přezutí, jehož nasazené pneumatiky ještě nikdo nesundal."""
        return all(m.removed_date is None for m in swap.mounted)

    def delete(self, swap):
        if not self.can_delete(swap):
            raise ValidationError("Pneumatiky z tohoto přezutí už byly později sundány – nejdřív smažte novější přezutí.")
        for mount in list(swap.removed):
            mount.removed_swap = None
            mount.removed_date = mount.removed_km = mount.removed_tread_mm = mount.removed_treads = None
        service_record = swap.service_record
        self.session.delete(swap)
        if service_record is not None:
            self.session.delete(service_record)
        self.session.commit()

    def _sync_service(self, swap, price, service_place):
        """Přezutí v servisu = servisní záznam (náklady, historie servisu); doma žádný."""
        services = ServiceRecordService(self.session)
        if swap.place != "service":
            if swap.service_record is not None:
                record = swap.service_record
                swap.service_record = None
                services.delete(record)
            return
        mounted = ", ".join(f"{m.tire.label} ({m.position_label.lower()})" for m in swap.mounted)
        data = {"vehicle_id": swap.vehicle_id, "service_date": swap.swap_date, "odometer": swap.odometer,
                "service_type": TIRE_SERVICE_TYPE, "place": _clean_str(service_place, 100, "Servis"),
                "note": f"Nasazeno: {mounted}" if mounted else "Sundání pneumatik",
                **(price if _has_price(price) else {"price_paid": None, "currency_code": "CZK", "manual_rate": None})}
        if swap.service_record is not None:
            services.update(swap.service_record, data)
        else:
            swap.service_record = services.create(**data)


# ----------------------------------------------------------------------
# Poškození
# ----------------------------------------------------------------------

class TireDefectService:
    def __init__(self, session):
        self.session = session

    def get(self, defect_id):
        return self.session.get(TireDefect, defect_id)

    def for_tires(self, tire_ids):
        if not tire_ids:
            return []
        return (self.session.query(TireDefect).filter(TireDefect.tire_id.in_(tire_ids))
                .order_by(TireDefect.defect_date.desc(), TireDefect.id.desc()).all())

    @staticmethod
    def vehicle_on(tire, on_date):
        """Vozidlo, na kterém byla pneumatika k danému dni."""
        for m in reversed(tire.mounts):
            if m.mounted_date <= on_date and (m.removed_date is None or m.removed_date >= on_date):
                return m.vehicle_id
        return None

    def save(self, defect, tire, data, price, vehicle_id):
        if not data.get("defect_date"):
            raise ValidationError("Datum poškození je povinné.")
        vehicle_id = vehicle_id or self.vehicle_on(tire, data["defect_date"])
        if _has_price(price) and not vehicle_id:
            raise ValidationError("Pro zápis ceny opravy vyberte vozidlo (výdaj patří k vozidlu).")
        odometer = _positive_int(data.get("odometer"), "Stav tachometru")
        if vehicle_id:
            check_odometer_order(self.session, vehicle_id, data["defect_date"], odometer,
                                 exclude=("tire_defect", defect.id if defect else None))
        values = {
            "tire_id": tire.id, "vehicle_id": vehicle_id, "defect_date": data["defect_date"],
            "odometer": odometer,
            "position": _clean_str(data.get("position"), 20, "Pozice"),
            "description": _clean_str(data.get("description"), 200, "Popis", required=True),
        }
        if defect is None:
            defect = TireDefect(**values)
            self.session.add(defect)
        else:
            for key, value in values.items():
                setattr(defect, key, value)
        self.session.commit()
        _sync_expense(self.session, defect, price, vehicle_id, defect.defect_date,
                      f"Oprava pneumatiky: {defect.description}", defect.odometer)
        self.session.commit()
        return defect

    def delete(self, defect):
        expense = defect.expense
        self.session.delete(defect)
        if expense is not None:
            self.session.delete(expense)
        self.session.commit()


# ----------------------------------------------------------------------
# Průběžné kontroly dezénu
# ----------------------------------------------------------------------

def mounts_on(session, vehicle_id, day):
    """Pneumatiky na vozidle k danému dni (v den přezutí už ty nové)."""
    mounts = (session.query(TireMount).options(joinedload(TireMount.tire))
              .filter(TireMount.vehicle_id == vehicle_id, TireMount.mounted_date <= day)
              .filter((TireMount.removed_date.is_(None)) | (TireMount.removed_date > day)).all())
    order = list(TIRE_POSITIONS)
    return sorted(mounts, key=lambda m: (order.index(m.position) if m.position in order else 99, m.id))


def wheel_layout(vehicle, mounts):
    """Kola vozidla pro nákres: [{"key", "short", "label", "mount"}] (mount None = prázdné kolo)."""
    result = []
    if vehicle.kind == "moto":
        for key, short, label in MOTO_WHEELS:
            slot = "fl" if key == "f" else "rl"
            result.append({"key": key, "short": short, "label": f"{label} kolo",
                           "mount": next((m for m in mounts if slot in m.slots), None)})
    else:
        for key, short, label in CAR_WHEELS:
            result.append({"key": key, "short": short, "label": label,
                           "mount": next((m for m in mounts if key in m.slots), None)})
    return result


def last_readings(session, mount_ids, before_check_id=None):
    """Poslední naměřený dezén pro každé kolo: {(id nasazení, kolo): (mm, datum)}."""
    if not mount_ids:
        return {}
    query = (session.query(TireTreadReading, TireTreadCheck.check_date).join(TireTreadReading.check)
             .filter(TireTreadReading.mount_id.in_(mount_ids)))
    if before_check_id:
        query = query.filter(TireTreadCheck.id != before_check_id)
    result = {}
    for reading, day in query.order_by(TireTreadCheck.check_date, TireTreadCheck.id):
        result[(reading.mount_id, reading.wheel)] = (reading.tread_mm, day)
    return result


class TireTreadCheckService:
    def __init__(self, session):
        self.session = session

    def get(self, check_id):
        return self.session.get(TireTreadCheck, check_id)

    def for_vehicles(self, vehicle_ids, limit=None):
        if not vehicle_ids:
            return []
        query = (self.session.query(TireTreadCheck).filter(TireTreadCheck.vehicle_id.in_(vehicle_ids))
                 .order_by(TireTreadCheck.check_date.desc(), TireTreadCheck.id.desc()))
        return query.limit(limit).all() if limit else query.all()

    def save(self, check, vehicle, check_date, odometer, note, values, user=None):
        """values = {(id nasazení, kolo): mm}; prázdné hodnoty se ignorují."""
        if not check_date:
            raise ValidationError("Datum kontroly je povinné.")
        if check_date > date.today():
            raise ValidationError("Datum kontroly nemůže být v budoucnosti.")
        odometer = _positive_int(odometer, "Stav tachometru", allow_none=False)
        check_odometer_order(self.session, vehicle.id, datetime.combine(check_date, datetime.min.time()), odometer,
                             has_time=False, exclude=("tread_check", check.id if check else None))
        mounts = {m.id: m for m in mounts_on(self.session, vehicle.id, check_date)}
        if check is not None:  # při úpravě i pneumatiky z původní kontroly
            mounts.update({r.mount.id: r.mount for r in check.readings if r.mount is not None})
        readings = []
        for (mount_id, wheel), mm in values.items():
            mm = _tread(mm)
            if mm is None:
                continue
            mount = mounts.get(mount_id)
            if mount is None:
                raise ValidationError("K tomuto datu byly na voze jiné pneumatiky – zkontrolujte datum kontroly.")
            if wheel not in [w[0] for w in mount.wheels]:
                raise ValidationError("Neplatné kolo.")
            if odometer < mount.mounted_km:
                raise ValidationError(f"Pneumatika {mount.tire.label} byla nasazena až při {mount.mounted_km} km.")
            readings.append(TireTreadReading(tire_id=mount.tire_id, mount_id=mount.id, wheel=wheel, tread_mm=mm))
        if not readings:
            raise ValidationError("Zapište hloubku dezénu alespoň u jednoho kola.")
        if check is None:
            check = TireTreadCheck(vehicle_id=vehicle.id, created_by_id=user.id if user else None)
            self.session.add(check)
        check.check_date, check.odometer, check.note = check_date, odometer, _clean_str(note)
        check.readings = readings
        self.session.commit()
        return check

    def delete(self, check):
        self.session.delete(check)
        self.session.commit()


# ----------------------------------------------------------------------
# Životnost a upozornění
# ----------------------------------------------------------------------

TREAD_WARN_KM = 5000  # upozornit, když do zákonného minima zbývá méně km
WEAR_MIN_KM = 3000    # opotřebení počítat až z delšího úseku - z pár set km je odhad nesmyslný

def tire_stats(session, tires, today=None):
    """Statistika pneumatik: najeto, nasazení, vozidla, dezén, opotřebení, odhad konce vzorku, náklady, varování.

    Dezén se bere z kontrol dezénu i z měření při sundání (vždy nejmenší hodnota z kol). Opotřebení
    se počítá od dezénu při nákupu (případně od prvního měření) k poslednímu měření.
    """
    from services.stats_service import StatsService
    from services.vehicle_service import VehicleService
    today = today or date.today()
    vehicles = VehicleService(session)
    odometers, yearly = {}, {}

    def odometer(vehicle_id):
        if vehicle_id not in odometers:
            odometers[vehicle_id] = vehicles.get_current_odometer(vehicle_id)
        return odometers[vehicle_id]

    def km_per_year(vehicle_id):
        if vehicle_id not in yearly:
            yearly[vehicle_id] = StatsService(session).usage_profile(vehicle_id).get("km_per_year")
        return yearly[vehicle_id]

    result = []
    for tire in tires:
        km, days, measurements, vehicle_names = 0, 0, [], []
        checks = {}  # id nasazení -> {kontrola: nejmenší dezén}
        for r in tire.tread_readings:
            if r.mount_id is not None:
                per_mount = checks.setdefault(r.mount_id, {})
                per_mount[r.check] = min(per_mount.get(r.check, r.tread_mm), r.tread_mm)
        for m in tire.mounts:
            for check, mm in checks.get(m.id, {}).items():
                measurements.append((check.check_date, km + max(check.odometer - m.mounted_km, 0), mm))
            end_km = m.removed_km if m.removed_date else odometer(m.vehicle_id)
            if end_km is not None and end_km >= m.mounted_km:
                km += end_km - m.mounted_km
            days += max(((m.removed_date or today) - m.mounted_date).days, 0)
            if m.removed_tread_mm is not None:
                measurements.append((m.removed_date, km, m.removed_tread_mm))
            if m.vehicle.short_name not in vehicle_names:
                vehicle_names.append(m.vehicle.short_name)
        measurements.sort(key=lambda x: (x[0], x[1]))
        last = measurements[-1] if measurements else None
        if tire.new_tread_mm is not None:
            base = (tire.purchase_date, 0, tire.new_tread_mm)
        else:
            base = measurements[0] if len(measurements) > 1 else None
        minimum = Decimal(str(tire.min_tread))
        custom = tire.min_tread_mm is not None
        wear = remaining_km = remaining_months = None
        if base is not None and last is not None and last[1] - base[1] >= WEAR_MIN_KM and base[2] > last[2]:
            wear = (base[2] - last[2]) / Decimal(last[1] - base[1]) * 1000  # mm na 1000 km
            above = last[2] - minimum
            # odhad od posledního měření, ponížený o km najeté od té doby
            remaining_km = max(int(above / wear * 1000) - (km - last[1]), 0) if above > 0 else 0
        cost = (tire.price_local or Decimal("0")) + sum(
            (d.expense.price_local or 0 for d in tire.defects if d.expense), Decimal("0"))
        mount = tire.open_mount
        status = "retired" if tire.retired_date else ("mounted" if mount else "stored")
        if mount and remaining_km and km_per_year(mount.vehicle_id):
            remaining_months = remaining_km / km_per_year(mount.vehicle_id) * 12
        tread = last[2] if last else tire.new_tread_mm
        warnings = []
        if status != "retired":
            when = f" (≈ {_months_text(remaining_months)})" if remaining_months is not None else ""
            if tread is not None and tread <= minimum:
                warnings.append(("danger", f"dezén {_mm(tread)} mm – pod {'nastaveným' if custom else 'zákonným'} minimem {_mm(minimum)} mm"))
            elif remaining_km == 0:
                warnings.append(("danger", "podle opotřebení už je vzorek na minimu – změřte dezén"))
            elif remaining_km is not None and remaining_km < TREAD_WARN_KM:
                warnings.append(("warning", f"vzorek dojde za ≈ {remaining_km:,} km{when}".replace(",", " ")))
            elif tread is not None and tread <= minimum + 1:
                warnings.append(("warning", f"dezén {_mm(tread)} mm – blíží se "
                                            f"{'nastavenému' if custom else 'zákonnému'} minimu {_mm(minimum)} mm"))
            if tire.age_years is not None and tire.age_years >= TIRE_MAX_AGE_YEARS:
                warnings.append(("warning", f"stáří {tire.age_years} let – doporučená výměna"))
        result.append({
            "tire": tire, "status": status, "mount": mount, "km": km, "days": days,
            "used_years": round(days / 365.25, 1) if days else 0, "mounts": len(tire.mounts),
            "vehicles": vehicle_names, "tread": tread, "tread_date": last[0] if last else None,
            "measurements": len(measurements), "wear": wear, "remaining_km": remaining_km,
            "remaining_months": remaining_months,
            "cost": cost, "cost_per_1000": (cost / km * 1000) if km and cost else None, "warnings": warnings,
        })
    return result


def _mm(value):
    return f"{Decimal(str(value)):.1f}".replace(".", ",")


def _months_text(months):
    if months < 1.5:
        return "měsíc"
    if months < 18:
        return f"{round(months)} měs."
    return f"{months / 12:.1f} roku".replace(".", ",")


def winter_tire_status(today=None):
    """Zimní pneumatiky jsou povinné 1. 11. – 31. 3. (při zimních podmínkách); od 15. 10. upozornit."""
    today = today or date.today()
    if today.month in (11, 12, 1, 2, 3):
        start = date(today.year if today.month >= 11 else today.year - 1, 11, 1)
        return DueStatus(level=LEVEL_OVERDUE, due_date=start, days_left=(start - today).days,
                         text="nasazené letní v zimním období (1. 11. – 31. 3.)")
    if today.month == 10 and today.day >= 15:
        start = date(today.year, 11, 1)
        days = (start - today).days
        return DueStatus(level=LEVEL_WARNING, due_date=start, days_left=days,
                         text=f"nasazené letní, zimní povinné od 1. 11. (za {days} dní)")
    return None


def tire_alerts(session, vehicles, today=None):
    """[(vozidlo, pneumatika, DueStatus)] - aktivní auta s nasazenými letními pneu v zimním období
    (motorky zimní pneumatiky nepotřebují)."""
    status = winter_tire_status(today)
    if status is None:
        return []
    result = []
    for vehicle in vehicles:
        if not vehicle.in_use or vehicle.kind == "moto":
            continue
        summer = [m for m in open_mounts(session, vehicle.id) if m.tire.season == "Letní" and m.position != "spare"]
        if summer:
            result.append((vehicle, summer[0].tire, status))
    return result
