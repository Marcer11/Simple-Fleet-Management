"""Pneumatiky: sady, přezutí (doma / v servisu), poškození, životnost a upozornění."""
from datetime import date, datetime
from decimal import Decimal

from models import Expense, ServiceRecord, TireChange, TireDamage, TireSet
from models.tire import (
    TIRE_EXPENSE_CATEGORY, TIRE_MAX_AGE_YEARS, TIRE_PLACES, TIRE_RIMS, TIRE_SEASONS, TIRE_SERVICE_TYPE,
)
from services.errors import ValidationError, NotFoundError
from services.maintenance_service import (
    DueStatus, ExpenseService, ServiceRecordService, LEVEL_OVERDUE, LEVEL_WARNING, _RecordServiceBase,
    _clean_str, _ensure_vehicle, _positive_int, check_odometer_order,
)
from services.pricing import to_decimal

PRICE_KEYS = ("price_paid", "currency_code", "manual_rate")
TREAD_MAX = Decimal("20")


def _pop_price(data):
    price = {key: data.pop(key, None) for key in PRICE_KEYS}
    has_price = price["price_paid"] not in (None, "")
    return price if has_price else None


def _tread(value, label):
    value = to_decimal(value, Decimal("0.1"))
    if value is not None and not (0 <= value <= TREAD_MAX):
        raise ValidationError(f"{label} musí být 0–20 mm.")
    return value


def _get_set(session, tire_set_id, vehicle_id):
    tire_set = session.get(TireSet, tire_set_id) if tire_set_id else None
    if tire_set is None or tire_set.vehicle_id != vehicle_id:
        raise ValidationError("Vyberte sadu pneumatik tohoto vozidla.")
    return tire_set


def _sync_expense(session, owner, price, expense_date, description, odometer=None):
    """Výdaj navázaný na sadu / poškození: založí, upraví, nebo (bez ceny) smaže."""
    expenses = ExpenseService(session)
    if price is None:
        if owner.expense is not None:
            expense = owner.expense
            owner.expense_id = None
            expenses.delete(expense)
        return
    data = {"vehicle_id": owner.vehicle_id, "expense_date": expense_date, "category": TIRE_EXPENSE_CATEGORY,
            "description": description[:200], "odometer": odometer, **price}
    if owner.expense is not None:
        expenses.update(owner.expense, data)
    else:
        owner.expense = expenses.create(**data)
        session.commit()


# ----------------------------------------------------------------------
# Sady pneumatik
# ----------------------------------------------------------------------

class TireSetService(_RecordServiceBase):
    model = TireSet
    date_column = "purchase_date"

    def create(self, **data):
        price = _pop_price(data)
        record = super().create(**data)
        self._sync(record, price)
        return record

    def update(self, record, data):
        data = dict(data)
        price = _pop_price(data)
        record = super().update(record, data)
        self._sync(record, price)
        return record

    def _sync(self, record, price):
        description = f"Nákup pneumatik: {record.full_label}"
        _sync_expense(self.session, record, price, record.purchase_date or date.today(), description)

    def delete(self, record):
        """Smaže sadu včetně přezutí a poškození i výdajů a servisů, které k nim aplikace založila."""
        linked = [record.expense] + [d.expense for d in record.damages] \
            + [c.service_record for c in record.changes]
        self.session.delete(record)
        self.session.flush()
        for item in linked:
            if item is not None:
                self.session.delete(item)
        self.session.commit()

    def _validate(self, data):
        _ensure_vehicle(self.session, data.get("vehicle_id"))
        season = data.get("season")
        if season not in TIRE_SEASONS:
            raise ValidationError("Vyberte typ pneumatik (letní, zimní, univerzální).")
        rim = data.get("rim") or ""
        if rim not in TIRE_RIMS:
            raise ValidationError("Neplatný typ disků.")
        year = data.get("production_year")
        if year not in (None, "") and not (1990 <= int(year) <= date.today().year + 1):
            raise ValidationError("Neplatný rok výroby pneumatik.")
        quantity = _positive_int(data.get("quantity"), "Počet kusů") or 4
        if not 1 <= quantity <= 20:
            raise ValidationError("Počet kusů musí být 1–20.")
        retired = data.get("retired_date")
        if retired and data.get("purchase_date") and retired < data["purchase_date"]:
            raise ValidationError("Vyřazení nemůže být před nákupem.")
        return {
            "vehicle_id": data["vehicle_id"],
            "season": season,
            "manufacturer": _clean_str(data.get("manufacturer"), 50, "Výrobce", required=True),
            "model": _clean_str(data.get("model"), 50, "Model"),
            "size": _clean_str(data.get("size"), 30, "Rozměr"),
            "production_year": int(year) if year not in (None, "") else None,
            "dot": _clean_str(data.get("dot"), 10, "DOT"),
            "quantity": quantity,
            "rim": rim,
            "new_tread_mm": _tread(data.get("new_tread_mm"), "Hloubka dezénu"),
            "purchase_date": data.get("purchase_date"),
            "storage_location": _clean_str(data.get("storage_location"), 100, "Místo uložení"),
            "retired_date": retired,
            "retired_reason": _clean_str(data.get("retired_reason"), 200, "Důvod vyřazení") if retired else None,
            "note": _clean_str(data.get("note")),
        }

    def list_for_vehicles(self, vehicle_ids, include_retired=True):
        if not vehicle_ids:
            return []
        query = self.session.query(TireSet).filter(TireSet.vehicle_id.in_(vehicle_ids))
        if not include_retired:
            query = query.filter(TireSet.retired_date.is_(None))
        return query.order_by(TireSet.retired_date.isnot(None), TireSet.season, TireSet.id).all()


# ----------------------------------------------------------------------
# Přezutí
# ----------------------------------------------------------------------

class TireChangeService(_RecordServiceBase):
    model = TireChange
    date_column = "change_date"

    def create(self, **data):
        price = _pop_price(data)
        service_place = data.pop("service_place", None)
        record = super().create(**data)
        self._sync_service(record, price, service_place)
        return record

    def update(self, record, data):
        data = {**data, "id": record.id}
        price = _pop_price(data)
        service_place = data.pop("service_place", None)
        record = super().update(record, data)
        self._sync_service(record, price, service_place)
        return record

    def delete(self, record):
        service_record = record.service_record
        self.session.delete(record)
        if service_record is not None:
            self.session.delete(service_record)
        self.session.commit()

    def _sync_service(self, record, price, service_place):
        """Přezutí v servisu = servisní záznam (náklady, servisní historie); doma žádný."""
        services = ServiceRecordService(self.session)
        if record.place != "service":
            if record.service_record is not None:
                service_record = record.service_record
                record.service_record_id = None
                services.delete(service_record)
            return
        data = {"vehicle_id": record.vehicle_id, "service_date": record.change_date, "odometer": record.odometer,
                "service_type": TIRE_SERVICE_TYPE, "place": service_place,
                "note": f"Nasazeno: {record.tire_set.full_label}",
                **(price or {"price_paid": None, "currency_code": "CZK", "manual_rate": None})}
        if record.service_record is not None:
            services.update(record.service_record, data)
        else:
            record.service_record = services.create(**data)
            self.session.commit()

    def _validate(self, data):
        _ensure_vehicle(self.session, data.get("vehicle_id"))
        if not data.get("change_date"):
            raise ValidationError("Datum přezutí je povinné.")
        odometer = _positive_int(data.get("odometer"), "Stav tachometru", allow_none=False)
        tire_set = _get_set(self.session, data.get("tire_set_id"), data["vehicle_id"])
        place = data.get("place") or "home"
        if place not in TIRE_PLACES:
            raise ValidationError("Neplatné místo přezutí.")
        check_odometer_order(self.session, data["vehicle_id"], datetime.combine(data["change_date"], datetime.min.time()),
                             odometer, has_time=False, exclude=("tire_change", data.get("id")))
        return {
            "vehicle_id": data["vehicle_id"],
            "change_date": data["change_date"],
            "odometer": odometer,
            "tire_set_id": tire_set.id,
            "place": place,
            "removed_tread_mm": _tread(data.get("removed_tread_mm"), "Hloubka dezénu"),
            "note": _clean_str(data.get("note")),
        }

    def for_vehicle(self, vehicle_id):
        return (self.session.query(TireChange).filter(TireChange.vehicle_id == vehicle_id)
                .order_by(TireChange.change_date, TireChange.odometer, TireChange.id).all())

    def mounted_set(self, vehicle_id, on_date=None):
        """Sada nasazená k danému dni (podle posledního přezutí), jinak None."""
        query = self.session.query(TireChange).filter(TireChange.vehicle_id == vehicle_id)
        if on_date:
            query = query.filter(TireChange.change_date <= on_date)
        last = query.order_by(TireChange.change_date.desc(), TireChange.odometer.desc(),
                              TireChange.id.desc()).first()
        return last.tire_set if last else None


# ----------------------------------------------------------------------
# Poškození
# ----------------------------------------------------------------------

class TireDamageService(_RecordServiceBase):
    model = TireDamage
    date_column = "damage_date"

    def create(self, **data):
        price = _pop_price(data)
        record = super().create(**data)
        self._sync(record, price)
        return record

    def update(self, record, data):
        data = dict(data)
        price = _pop_price(data)
        record = super().update(record, data)
        self._sync(record, price)
        return record

    def _sync(self, record, price):
        _sync_expense(self.session, record, price, record.damage_date,
                      f"Oprava pneumatiky: {record.description}", record.odometer)

    def delete(self, record):
        expense = record.expense
        self.session.delete(record)
        if expense is not None:
            self.session.delete(expense)
        self.session.commit()

    def _validate(self, data):
        _ensure_vehicle(self.session, data.get("vehicle_id"))
        if not data.get("damage_date"):
            raise ValidationError("Datum poškození je povinné.")
        tire_set = _get_set(self.session, data.get("tire_set_id"), data["vehicle_id"])
        return {
            "vehicle_id": data["vehicle_id"],
            "tire_set_id": tire_set.id,
            "damage_date": data["damage_date"],
            "odometer": _positive_int(data.get("odometer"), "Stav tachometru"),
            "position": _clean_str(data.get("position"), 20, "Pozice"),
            "description": _clean_str(data.get("description"), 200, "Popis", required=True),
        }


# ----------------------------------------------------------------------
# Životnost a upozornění
# ----------------------------------------------------------------------

def tire_overview(session, vehicle, current_odometer=None, today=None):
    """Sady vozidla se statistikou: najeto, sezóny, dny na voze, dezén, opotřebení, náklady."""
    today = today or date.today()
    sets = TireSetService(session).list_for_vehicles([vehicle.id])
    changes = TireChangeService(session).for_vehicle(vehicle.id)
    stats = {s.id: {"km": 0, "days": 0, "seasons": 0, "measurements": [], "first_mounted": None,
                    "last_removed": None} for s in sets}

    # období na voze: od přezutí do dalšího přezutí (poslední až do dneška / aktuálního stavu)
    for i, change in enumerate(changes):
        nxt = changes[i + 1] if i + 1 < len(changes) else None
        end_date = nxt.change_date if nxt else today
        end_km = nxt.odometer if nxt else current_odometer
        s = stats.get(change.tire_set_id)
        if s is None:
            continue
        s["seasons"] += 1
        s["days"] += max((end_date - change.change_date).days, 0)
        s["first_mounted"] = s["first_mounted"] or change.change_date
        if end_km is not None and end_km >= change.odometer:
            s["km"] += end_km - change.odometer
        if nxt is not None:
            s["last_removed"] = nxt.change_date
            if nxt.removed_tread_mm is not None:  # měření sundané sady
                s["measurements"].append((s["km"], nxt.removed_tread_mm, nxt.change_date))

    mounted = changes[-1].tire_set_id if changes else None
    result = []
    for tire_set in sets:
        s = stats[tire_set.id]
        first = tire_set.new_tread_mm
        last = s["measurements"][-1] if s["measurements"] else None
        wear = None   # mm na 1000 km
        remaining_km = None
        if first is not None and last is not None and last[0] > 0 and first > last[1]:
            wear = (first - last[1]) / Decimal(last[0]) * 1000
            above = last[1] - Decimal(str(tire_set.legal_min_tread))
            remaining_km = int(above / wear * 1000) if above > 0 else 0
        cost = Decimal("0")
        if tire_set.expense is not None and tire_set.expense.price_local is not None:
            cost += tire_set.expense.price_local
        damage_cost = sum((d.expense.price_local or 0 for d in tire_set.damages if d.expense), Decimal("0"))
        status = "retired" if tire_set.retired_date else ("mounted" if tire_set.id == mounted else "stored")
        warnings = []
        tread = last[1] if last else first
        if tread is not None and status != "retired":
            minimum = Decimal(str(tire_set.legal_min_tread))
            if tread <= minimum:
                warnings.append(("danger", f"dezén {tread} mm – pod zákonným minimem {tire_set.legal_min_tread} mm"))
            elif tread <= minimum + 1:
                warnings.append(("warning", f"dezén {tread} mm – blíží se minimum {tire_set.legal_min_tread} mm"))
        if tire_set.age_years is not None and tire_set.age_years >= TIRE_MAX_AGE_YEARS and status != "retired":
            warnings.append(("warning", f"stáří {tire_set.age_years} let – doporučená výměna"))
        result.append({
            "set": tire_set, "status": status, "km": s["km"], "days": s["days"], "seasons": s["seasons"],
            "tread": tread, "measurements": s["measurements"], "wear": wear, "remaining_km": remaining_km,
            "cost": cost + damage_cost, "damage_cost": damage_cost,
            "cost_per_1000": ((cost + damage_cost) / s["km"] * 1000) if s["km"] and cost + damage_cost else None,
            "used_years": round(s["days"] / 365.25, 1) if s["days"] else 0,
            "first_mounted": s["first_mounted"], "warnings": warnings,
        })
    order = {"mounted": 0, "stored": 1, "retired": 2}
    result.sort(key=lambda r: (order[r["status"]], r["set"].season, r["set"].id))
    return result


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
    """[(vozidlo, sada, DueStatus)] - aktivní vozidla, která mají v zimním období nasazené letní pneu."""
    status = winter_tire_status(today)
    if status is None:
        return []
    service = TireChangeService(session)
    result = []
    for vehicle in vehicles:
        if not vehicle.is_active:
            continue
        mounted = service.mounted_set(vehicle.id, today)
        if mounted is not None and mounted.season == "Letní":
            result.append((vehicle, mounted, status))
    return result
