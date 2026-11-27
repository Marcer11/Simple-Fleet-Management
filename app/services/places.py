"""Místa: servisy, čerpací stanice a místa výdajů.

Místo je dané názvem zapsaným u záznamu (servis: místo, tankování: stanice + adresa, výdaj: místo);
stejný název s jinou velikostí písmen nebo mezerami je stejné místo. Pumpa se rozlišuje podle adresy
(bez adresy podle názvu) - stejně jako v přehledu čerpacích stanic.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from models import Expense, FuelRecord, ServiceRecord
from services.stations import station_brand

ZERO = Decimal("0")
KINDS = {"service": "Servisy", "station": "Čerpací stanice", "expense": "Místa výdajů"}
KIND_LABELS = {"service": "Servis", "station": "Čerpací stanice", "expense": "Místo výdaje"}


def normalize(text):
    return " ".join((text or "").split())


def place_key(text):
    return normalize(text).lower()


def station_key(name, address):
    """Pumpa se pozná podle adresy; tankování bez adresy jsou jedno místo za značku („MOL – bez adresy“)."""
    if place_key(address):
        return place_key(address)
    return "~" + station_brand(name).lower()


def _station_label(summary):
    if not summary["address"]:
        summary["name"] = f"{station_brand(summary['name'])} – bez adresy"
    return summary


def place_url(kind, name, address=None):
    """Odkaz na detail místa (None, když název chybí)."""
    key = station_key(name, address) if kind == "station" else place_key(name)
    return f"/places/{kind}?{urlencode({'key': key})}" if key else None


@dataclass
class Visit:
    kind: str
    when: datetime
    has_time: bool
    vehicle: object
    title: str
    detail: str
    odometer: int
    amount: Decimal
    url: str
    name: str
    address: str = ""
    volume: Decimal = None
    unit: str = None


def _records(session, kind, vehicle_ids, date_from=None, date_to=None):
    if not vehicle_ids:
        return []
    if kind == "service":
        model, column = ServiceRecord, ServiceRecord.service_date
        query = session.query(model).filter(model.vehicle_id.in_(vehicle_ids), model.place.isnot(None))
    elif kind == "expense":
        model, column = Expense, Expense.expense_date
        query = session.query(model).filter(model.vehicle_id.in_(vehicle_ids), model.place.isnot(None))
    else:
        model, column = FuelRecord, FuelRecord.refuel_datetime
        query = session.query(model).filter(model.vehicle_id.in_(vehicle_ids))
    datetime_column = kind == "station"
    if date_from:
        query = query.filter(column >= (datetime.combine(date_from, time.min) if datetime_column else date_from))
    if date_to:
        query = query.filter(column < (datetime.combine(date_to + timedelta(days=1), time.min))
                             if datetime_column else column <= date_to)
    return query.all()


def _visit(kind, r):
    if kind == "service":
        return Visit(kind, datetime.combine(r.service_date, r.service_time or time.min), r.service_time is not None,
                     r.vehicle, r.service_type, r.duration and f"v servisu {r.duration}" or "", r.odometer,
                     r.own_cost, f"/services/{r.id}", normalize(r.place))
    if kind == "expense":
        return Visit(kind, datetime.combine(r.expense_date, time.min), False, r.vehicle, r.category,
                     normalize(r.description), r.odometer, r.own_cost, f"/expenses/{r.id}", normalize(r.place))
    volume = f"{r.volume_liters:.2f}".rstrip("0").rstrip(".").replace(".", ",") if r.volume_liters else ""
    return Visit(kind, r.refuel_datetime, True, r.vehicle, r.fuel_type, f"{volume} {r.unit}" if volume else "",
                 r.odometer, r.price_local, f"/fuel-records/{r.id}", normalize(r.station_name),
                 normalize(r.station_address), r.volume_liters, r.unit)


def _key(kind, visit):
    return station_key(visit.name, visit.address) if kind == "station" else place_key(visit.name)


def visits(session, kind, vehicle_ids, key, date_from=None, date_to=None):
    """Návštěvy jednoho místa, nejnovější nahoře."""
    result = [v for v in (_visit(kind, r) for r in _records(session, kind, vehicle_ids, date_from, date_to))
              if _key(kind, v) == key]
    return sorted(result, key=lambda v: v.when, reverse=True)


def _summary(items):
    names = Counter(v.name for v in items if v.name)
    addresses = Counter(v.address for v in items if v.address)
    cost = sum((v.amount or ZERO for v in items), ZERO)
    return {
        "name": names.most_common(1)[0][0] if names else "",
        "address": addresses.most_common(1)[0][0] if addresses else "",
        "count": len(items), "cost": cost,
        "first": min(v.when for v in items) if items else None,
        "last": max(v.when for v in items) if items else None,
        "vehicles": sorted({v.vehicle.short_name for v in items}),
    }


def overview(session, kind, vehicle_ids, date_from=None, date_to=None):
    """Místa daného druhu: [{key, name, address, count, cost, first, last, vehicles, url}], nejčastější nahoře."""
    groups = defaultdict(list)
    for r in _records(session, kind, vehicle_ids, date_from, date_to):
        visit = _visit(kind, r)
        key = _key(kind, visit)
        if key:
            groups[key].append(visit)
    result = []
    for key, items in groups.items():
        summary = _summary(items)
        summary.update(key=key, url=f"/places/{kind}?{urlencode({'key': key})}")
        if kind == "station":
            summary["brand"] = station_brand(summary["name"])
            _station_label(summary)
        result.append(summary)
    return sorted(result, key=lambda p: (-p["count"], -p["cost"], p["name"].lower()))


def detail(items):
    """Souhrn návštěv místa: celkem, po vozidlech a po letech."""
    summary = _summary(items)
    if items and items[0].kind == "station":
        summary["names"] = sorted({v.name for v in items if v.name})
        _station_label(summary)
    by_vehicle = defaultdict(list)
    by_year = defaultdict(list)
    for v in items:
        by_vehicle[v.vehicle.id].append(v)
        by_year[v.when.year].append(v)
    summary["by_vehicle"] = sorted(
        ({"vehicle": group[0].vehicle, "count": len(group), "cost": sum((v.amount or ZERO for v in group), ZERO),
          "last": max(v.when for v in group)} for group in by_vehicle.values()),
        key=lambda x: (-x["count"], x["vehicle"].short_name))
    summary["by_year"] = [(year, len(group), sum((v.amount or ZERO for v in group), ZERO))
                          for year, group in sorted(by_year.items(), reverse=True)]
    return summary


def known_names(session, kind, vehicle_ids):
    """Dříve zapsané názvy míst (nabídka ve formuláři), nejčastější první."""
    counter = Counter()
    spelled = {}
    for r in _records(session, kind, vehicle_ids):
        name = normalize(r.place if kind != "station" else r.station_name)
        if name:
            counter[name.lower()] += 1
            spelled.setdefault(name.lower(), name)
    return [spelled[k] for k, _ in counter.most_common()]


def fuel_volume(items):
    """Natankováno na pumpě: ({jednotka: množství}, průměrná cena za litr)."""
    volume = defaultdict(lambda: ZERO)
    priced_volume = priced_cost = ZERO
    for v in items:
        if v.unit:
            volume[v.unit] += v.volume or ZERO
        if v.amount is not None and v.volume and v.unit == "l":
            priced_volume += v.volume
            priced_cost += v.amount
    return dict(sorted(volume.items())), (priced_cost / priced_volume if priced_volume else None)
