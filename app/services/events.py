"""Časová osa vozidel: tankování, servis, výdaje, poznámky, nákup a prodej v jednom seznamu."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.orm import joinedload

from models import VehicleRental, Expense, FuelRecord, ServiceRecord, TireDefect, TireSwap, TireTreadCheck, Vehicle, VehicleNote

KIND_FUEL = "fuel"
KIND_SERVICE = "service"
KIND_EXPENSE = "expense"
KIND_NOTE = "note"
KIND_VEHICLE = "vehicle"
KIND_TIRES = "tires"
KIND_RENTAL = "rental"
KINDS = {
    KIND_FUEL: "Tankování",
    KIND_SERVICE: "Servis",
    KIND_EXPENSE: "Výdaje",
    KIND_RENTAL: "Půjčení",
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
    icon: str = None             # ikona v časové ose (viz _macros.event_icon)
    end_of_day: bool = False     # bez času řadit na konec dne (vrácení vozidla), jinak na začátek

    @property
    def order(self):
        """Řazení v rámci dne: záznamy bez času na začátku (vrácení na konci), mezi nimi podle času."""
        if self.has_time:
            rank = 1
        else:
            rank = 2 if self.end_of_day else 0
        return self.when.date(), rank, self.when.time(), self.odometer or 0

    def __post_init__(self):
        if self.icon is None:
            self.icon = {KIND_FUEL: "fuel", KIND_SERVICE: "service", KIND_EXPENSE: "expense", KIND_NOTE: "note",
                         KIND_VEHICLE: "car", KIND_TIRES: "tire", KIND_RENTAL: "key"}[self.kind]

    @property
    def kind_label(self):
        return {KIND_FUEL: "Tankování", KIND_SERVICE: "Servis", KIND_EXPENSE: "Výdaj",
                KIND_NOTE: "Poznámka", KIND_VEHICLE: "Vozidlo", KIND_TIRES: "Pneumatiky",
                KIND_RENTAL: "Půjčení"}[self.kind]


# Ikona podle typu poznámky / kategorie výdaje / položky servisu (porovnává se malými písmeny)
NOTE_ICONS = {"nehoda": "crash", "poškození": "warning", "nepojízdné": "stop", "opět pojízdné": "car", "garáž": "garage", "parkování": "parking",
              "půjčeno": "key", "vráceno": "key", "pneumatiky": "tire"}
EXPENSE_ICONS = {"pojištění": "shield", "parkování": "parking", "dálniční známka": "road", "mýtné": "road",
                 "pokuta": "warning", "pneumatiky": "tire", "mytí": "wash"}


def _note_icon(category):
    return NOTE_ICONS.get((category or "").strip().lower(), "note")


def _service_icon(types):
    lowered = [t.lower() for t in types]
    if lowered and all(t in ("stk", "emise") for t in lowered):
        return "stk"
    return "service"


def _insurance_text(r):
    if not r.insurance_claim:
        return ""
    text = "pojistná událost"
    if r.insurance_paid is not None:
        text = f"pojišťovna uhradila {int(round(r.insurance_paid)):,} Kč".replace(",", " ")
    return text + (f" ({r.insurer})" if r.insurer else "")


def _qty(value):
    value = Decimal(str(value)).normalize()
    text = f"{value:f}" if value != value.to_integral() else str(int(value))
    return text.replace(".", ",")


def _rental_title(action, rental):
    lender = rental.vehicle.lender or rental.provider
    return f"{action} – {lender}" if lender else action


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
                                r.odometer, r.price_local, f"/fuel-records/{r.id}"))

    # servis / výdaj založený přezutím nebo poškozením pneu se ukáže jen jako událost pneumatik
    tire_service_ids = {i for (i,) in session.query(TireSwap.service_record_id)
                        .filter(TireSwap.vehicle_id.in_(ids), TireSwap.service_record_id.isnot(None))}
    tire_expense_ids = {i for (i,) in session.query(TireDefect.expense_id)
                        .filter(TireDefect.vehicle_id.in_(ids), TireDefect.expense_id.isnot(None))}

    if KIND_TIRES in kinds:
        query = (session.query(TireSwap).options(joinedload(TireSwap.service_record))
                 .filter(TireSwap.vehicle_id.in_(ids)))
        for s in dated(query, TireSwap.swap_date, False):
            mounted = [m for m in s.mounted]
            new = [m for m in mounted if not any(r.tire_id == m.tire_id for r in s.removed)]
            parts = []
            if new:
                parts.append("nasazeno: " + ", ".join(f"{m.tire.label} ({m.position_label.lower()})" for m in new))
            removed = [m for m in s.removed if m.vehicle_id == s.vehicle_id
                       and not any(n.tire_id == m.tire_id for n in mounted)]
            if removed:
                parts.append("sundáno: " + ", ".join(
                    m.tire.label + (f" – dezén {m.treads_label} mm" if m.treads_label else "")
                    for m in removed))
            where = s.place_label + (f" – {s.service_record.place}" if s.service_record and s.service_record.place else "")
            parts.append(where)
            events.append(Event(KIND_TIRES, _day(s.swap_date), False, by_id[s.vehicle_id], "Přezutí pneumatik",
                                "\n".join(parts), s.odometer,
                                s.service_record.price_local if s.service_record else None,
                                f"/tire-swaps/{s.id}"))
        query = (session.query(TireDefect).options(joinedload(TireDefect.tire), joinedload(TireDefect.expense))
                 .filter(TireDefect.vehicle_id.in_(ids)))
        for d in dated(query, TireDefect.defect_date, False):
            detail = " · ".join(x for x in (d.tire.label, d.position) if x)
            events.append(Event(KIND_TIRES, _day(d.defect_date), False, by_id[d.vehicle_id],
                                f"Poškození pneu: {d.description}", detail, d.odometer,
                                d.expense.price_local if d.expense else None, f"/tire-defects/{d.id}",
                                icon="warning"))
        query = (session.query(TireTreadCheck).options(joinedload(TireTreadCheck.readings))
                 .filter(TireTreadCheck.vehicle_id.in_(ids)))
        for c in dated(query, TireTreadCheck.check_date, False):
            lines = [f"{tire.label}: " + " · ".join(r.text for r in readings) + " mm"
                     for tire, readings in c.by_tire()]
            detail = "\n".join(lines)
            events.append(Event(KIND_TIRES, _day(c.check_date), False, by_id[c.vehicle_id], "Kontrola dezénu",
                                detail, c.odometer, None, f"/tire-checks/{c.id}", icon="gauge"))

    # konec nepojízdnosti (poznámka "Opět pojízdné" nebo vyzvednutí ze servisu) ukáže, jak dlouho trvala
    ended = {}
    if KIND_SERVICE in kinds or KIND_NOTE in kinds:
        for v in vehicles:
            for period in v.out_of_order_periods:
                if period.end is not None:
                    ended[period.end_key] = period

    if KIND_SERVICE in kinds:
        query = session.query(ServiceRecord).filter(ServiceRecord.vehicle_id.in_(ids))
        if tire_service_ids:
            query = query.filter(ServiceRecord.id.notin_(tire_service_ids))
        # předání a vyzvednutí jsou dvě události, pokud vozidlo zůstalo v servisu přes den
        for r in query.all():
            url = f"/services/{r.id}"
            more_days = r.date_to is not None and r.date_to > r.service_date
            if in_range(_day(r.service_date)):
                stay = []
                if more_days:
                    stay.append(f"do {r.date_to.day}. {r.date_to.month}. {r.date_to.year}"
                                + (f" {r.time_to:%H:%M}" if r.time_to else ""))
                elif r.duration:
                    stay.append(f"v servisu {r.duration}")
                elif r.in_progress:
                    stay.append("zatím v servisu")
                if not more_days and r.distance is not None:
                    stay.append(f"servis najel {r.distance:,} km".replace(",", " "))
                if not more_days and ("service", r.id) in ended:
                    stay.append(f"opět pojízdné (nepojízdné {ended['service', r.id].duration})")
                detail = " · ".join(x for x in (r.place, *stay, _insurance_text(r)) if x)
                events.append(Event(KIND_SERVICE, datetime.combine(r.service_date, r.service_time or time(0, 0)),
                                    r.service_time is not None, by_id[r.vehicle_id], r.service_type,
                                    detail, r.odometer, r.own_cost, url, icon=_service_icon(r.types)))
            if more_days and in_range(_day(r.date_to)):
                parts = [f"v servisu {r.duration}"]
                if r.distance is not None:
                    parts.append(f"servis najel {r.distance:,} km".replace(",", " "))
                if ("service", r.id) in ended:
                    parts.append(f"opět pojízdné (nepojízdné {ended['service', r.id].duration})")
                title = "Vyzvednutí ze servisu" + (f" – {r.place}" if r.place else "")
                events.append(Event(KIND_SERVICE, datetime.combine(r.date_to, r.time_to or time(0, 0)),
                                    r.time_to is not None, by_id[r.vehicle_id], title, " · ".join(parts),
                                    r.odometer_to, None, url, icon="return", end_of_day=True))

    if KIND_EXPENSE in kinds:
        query = session.query(Expense).filter(Expense.vehicle_id.in_(ids))
        if tire_expense_ids:
            query = query.filter(Expense.id.notin_(tire_expense_ids))
        for r in dated(query, Expense.expense_date, False):
            parts = [r.description] if getattr(r, "description", None) else []
            if r.valid_until:
                parts.append(f"platí do {r.valid_until.day}. {r.valid_until.month}. {r.valid_until.year}")
            if r.insurance_claim:
                parts.append(_insurance_text(r))
            events.append(Event(KIND_EXPENSE, _day(r.expense_date), False, by_id[r.vehicle_id], r.category,
                                " · ".join(parts), r.odometer, r.own_cost, f"/expenses/{r.id}",
                                icon=EXPENSE_ICONS.get(r.category.lower(), "expense")))

    if KIND_RENTAL in kinds:
        query = session.query(VehicleRental).filter(VehicleRental.vehicle_id.in_(ids))
        # půjčení a vrácení jsou dvě události (vrácení jen se zapsaným koncem půjčení)
        for r in query.all():
            url = f"/rentals/{r.id}"
            if in_range(_day(r.date_from)):
                parts = [f"do {r.date_to.day}. {r.date_to.month}. {r.date_to.year}"
                         + (f" {r.time_to:%H:%M}" if r.time_to else "") if r.date_to else "zatím nevráceno"]
                events.append(Event(KIND_RENTAL, datetime.combine(r.date_from, r.time_from or time(0, 0)),
                                    r.time_from is not None, by_id[r.vehicle_id],
                                    _rental_title("Půjčení", r), " · ".join(parts), r.odometer_from,
                                    r.price_local, url))
            if r.date_to and in_range(_day(r.date_to)):
                parts = []
                if r.days:
                    parts.append(f"{r.days} {'den' if r.days == 1 else ('dny' if r.days < 5 else 'dní')}")
                if r.distance is not None:
                    parts.append(f"najeto {r.distance:,} km".replace(",", " "))
                # vrácení bez času patří na konec dne (po tankování a dalších záznamech toho dne)
                events.append(Event(KIND_RENTAL, datetime.combine(r.date_to, r.time_to or time(0, 0)),
                                    r.time_to is not None, by_id[r.vehicle_id],
                                    _rental_title("Vrácení", r), " · ".join(parts), r.odometer_to, None, url,
                                    icon="return", end_of_day=True))

    if KIND_NOTE in kinds:
        query = (session.query(VehicleNote).options(joinedload(VehicleNote.created_by))
                 .filter(VehicleNote.vehicle_id.in_(ids)))
        for n in dated(query, VehicleNote.note_datetime, True):
            detail = (n.text or "").strip() if n.category else "\n".join((n.text or "").strip().split("\n")[1:])
            if ("note", n.id) in ended:
                length = f"nepojízdné {ended['note', n.id].duration}"
                detail = f"{length} · {detail}" if detail else length
            if n.created_by:
                detail = f"{detail} ({n.created_by.name})" if detail else n.created_by.name
            events.append(Event(KIND_NOTE, n.note_datetime, True, by_id[n.vehicle_id], n.title, detail,
                                n.odometer, None, f"/notes/{n.id}", icon=_note_icon(n.category)))

    if KIND_VEHICLE in kinds:
        for v in vehicles:
            if v.purchase_date and in_range(_day(v.purchase_date)):
                events.append(Event(KIND_VEHICLE, _day(v.purchase_date), False, v, "Nákup vozidla",
                                    odometer=v.purchase_odometer, amount=v.purchase_price,
                                    url=f"/vehicles/{v.id}?tab=detail", icon="key"))
            if v.sale_date and in_range(_day(v.sale_date)):
                parts = []
                if v.value_loss is not None:
                    parts.append(f"ztráta hodnoty {_qty(v.value_loss)} Kč")
                if v.owned_km is not None:
                    parts.append(f"najeto za vlastnictví {v.owned_km:,} km".replace(",", " "))
                events.append(Event(KIND_VEHICLE, _day(v.sale_date), False, v, "Prodej vozidla", " · ".join(parts),
                                    odometer=v.sale_odometer, amount=v.sale_price, url=f"/vehicles/{v.id}?tab=detail"))

    # nejnovější nahoře; ve stejný den události s časem před celodenními
    events.sort(key=lambda e: e.order, reverse=True)
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
