"""Časová osa vozidel: tankování, servis, výdaje, poznámky, nákup a prodej v jednom seznamu."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.orm import joinedload

from models import Expense, FuelRecord, ServiceRecord, TireChange, TireDamage, Vehicle, VehicleNote

KIND_FUEL = "fuel"
KIND_SERVICE = "service"
KIND_EXPENSE = "expense"
KIND_NOTE = "note"
KIND_VEHICLE = "vehicle"
KIND_TIRES = "tires"
KINDS = {
    KIND_FUEL: "Tankování",
    KIND_SERVICE: "Servis",
    KIND_EXPENSE: "Výdaje",
    KIND_TIRES: "Pneumatiky",
    KIND_NOTE: "Poznámky",
    KIND_VEHICLE: "Nákup a prodej",
}


@dataclass
class Event:
    kind: str
    when: datetime
    has_time: bool
    vehicle: Vehicle
    title: str
    detail: str = ""
    odometer: int = None
    amount: Decimal = None       # Kč
    url: str = None              # úprava záznamu (jen pro editory)

    @property
    def kind_label(self):
        return {KIND_FUEL: "Tankování", KIND_SERVICE: "Servis", KIND_EXPENSE: "Výdaj",
                KIND_NOTE: "Poznámka", KIND_VEHICLE: "Vozidlo", KIND_TIRES: "Pneumatiky"}[self.kind]


def _qty(value):
    value = Decimal(str(value)).normalize()
    text = f"{value:f}" if value != value.to_integral() else str(int(value))
    return text.replace(".", ",")


def _day(d):
    return datetime.combine(d, time(0, 0))


def collect_events(session, vehicles, date_from=None, date_to=None, kinds=None, limit=None):
    """Události vybraných vozidel od nejnovější. date_from/date_to jsou date (včetně)."""
    kinds = set(kinds or KINDS)
    by_id = {v.id: v for v in vehicles}
    ids = list(by_id)
    if not ids:
        return []
    start = _day(date_from) if date_from else None
    end = _day(date_to + timedelta(days=1)) if date_to else None
    events = []

    def in_range(when):
        return (start is None or when >= start) and (end is None or when < end)

    def dated(query, column, is_datetime):
        if start is not None:
            query = query.filter(column >= (start if is_datetime else start.date()))
        if end is not None:
            query = query.filter(column < (end if is_datetime else end.date()))
        return query

    if KIND_FUEL in kinds:
        query = session.query(FuelRecord).filter(FuelRecord.vehicle_id.in_(ids))
        for r in dated(query, FuelRecord.refuel_datetime, True):
            detail = f"{_qty(r.volume_liters)} {r.unit}"
            if r.consumption is not None:
                detail += f" · spotřeba {_qty(r.consumption)} {r.unit}/100 km"
            if r.station_name:
                detail += f" · {r.station_name}"
            events.append(Event(KIND_FUEL, r.refuel_datetime, True, by_id[r.vehicle_id], r.fuel_type, detail,
                                r.odometer, r.price_local, f"/fuel-records/{r.id}/edit"))

    # servis / výdaj založený přezutím nebo poškozením pneu se ukáže jen jako událost pneumatik
    tire_service_ids = {i for (i,) in session.query(TireChange.service_record_id)
                        .filter(TireChange.vehicle_id.in_(ids), TireChange.service_record_id.isnot(None))}
    tire_expense_ids = {i for (i,) in session.query(TireDamage.expense_id)
                        .filter(TireDamage.vehicle_id.in_(ids), TireDamage.expense_id.isnot(None))}

    if KIND_TIRES in kinds:
        query = (session.query(TireChange).options(joinedload(TireChange.tire_set), joinedload(TireChange.service_record))
                 .filter(TireChange.vehicle_id.in_(ids)))
        for c in dated(query, TireChange.change_date, False):
            parts = [c.place_label + (f" – {c.service_record.place}" if c.service_record and c.service_record.place else "")]
            if c.removed_tread_mm is not None:
                parts.append(f"dezén sundané sady {_qty(c.removed_tread_mm)} mm")
            if c.note:
                parts.append(c.note.strip())
            amount = c.service_record.price_local if c.service_record else None
            events.append(Event(KIND_TIRES, _day(c.change_date), False, by_id[c.vehicle_id],
                                f"Přezutí: {c.tire_set.label}", " · ".join(parts), c.odometer, amount,
                                f"/tire-changes/{c.id}/edit"))
        query = (session.query(TireDamage).options(joinedload(TireDamage.tire_set), joinedload(TireDamage.expense))
                 .filter(TireDamage.vehicle_id.in_(ids)))
        for d in dated(query, TireDamage.damage_date, False):
            detail = " · ".join(x for x in (d.tire_set.label, d.position) if x)
            events.append(Event(KIND_TIRES, _day(d.damage_date), False, by_id[d.vehicle_id],
                                f"Poškození pneu: {d.description}", detail, d.odometer,
                                d.expense.price_local if d.expense else None, f"/tire-damages/{d.id}/edit"))

    if KIND_SERVICE in kinds:
        query = session.query(ServiceRecord).filter(ServiceRecord.vehicle_id.in_(ids))
        if tire_service_ids:
            query = query.filter(ServiceRecord.id.notin_(tire_service_ids))
        for r in dated(query, ServiceRecord.service_date, False):
            detail = " · ".join(x for x in (r.place, (r.note or "").strip()) if x)
            events.append(Event(KIND_SERVICE, _day(r.service_date), False, by_id[r.vehicle_id], r.service_type,
                                detail, r.odometer, r.price_local, f"/services/{r.id}/edit"))

    if KIND_EXPENSE in kinds:
        query = session.query(Expense).filter(Expense.vehicle_id.in_(ids))
        if tire_expense_ids:
            query = query.filter(Expense.id.notin_(tire_expense_ids))
        for r in dated(query, Expense.expense_date, False):
            parts = [r.description] if getattr(r, "description", None) else []
            if r.valid_until:
                parts.append(f"platí do {r.valid_until.day}. {r.valid_until.month}. {r.valid_until.year}")
            if r.note:
                parts.append(r.note.strip())
            events.append(Event(KIND_EXPENSE, _day(r.expense_date), False, by_id[r.vehicle_id], r.category,
                                " · ".join(parts), r.odometer, r.price_local, f"/expenses/{r.id}/edit"))

    if KIND_NOTE in kinds:
        query = (session.query(VehicleNote).options(joinedload(VehicleNote.created_by))
                 .filter(VehicleNote.vehicle_id.in_(ids)))
        for n in dated(query, VehicleNote.note_datetime, True):
            detail = (n.text or "").strip() if n.category else "\n".join((n.text or "").strip().split("\n")[1:])
            if n.created_by:
                detail = f"{detail} ({n.created_by.name})" if detail else n.created_by.name
            events.append(Event(KIND_NOTE, n.note_datetime, True, by_id[n.vehicle_id], n.title, detail,
                                n.odometer, None, f"/notes/{n.id}/edit"))

    if KIND_VEHICLE in kinds:
        for v in vehicles:
            if v.purchase_date and in_range(_day(v.purchase_date)):
                events.append(Event(KIND_VEHICLE, _day(v.purchase_date), False, v, "Nákup vozidla",
                                    amount=v.purchase_price, url=f"/vehicles/{v.id}/edit"))
            if v.sale_date and in_range(_day(v.sale_date)):
                detail = f"ztráta hodnoty {_qty(v.value_loss)} Kč" if v.value_loss is not None else ""
                events.append(Event(KIND_VEHICLE, _day(v.sale_date), False, v, "Prodej vozidla", detail,
                                    amount=v.sale_price, url=f"/vehicles/{v.id}/edit"))

    # nejnovější nahoře; ve stejný den události s časem před celodenními
    events.sort(key=lambda e: (e.when.date(), e.has_time, e.when.time(), e.odometer or 0), reverse=True)
    return events[:limit] if limit else events


def group_by_month(events):
    """[(date prvního dne měsíce, [události])] - pro nadpisy na časové ose."""
    groups = []
    for e in events:
        key = date(e.when.year, e.when.month, 1)
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(e)
    return groups
