"""Doplňkové přehledy statistik: po letech, kam jdou peníze, servis podle typu, nejčastější místa
a rekordy tankování. Platí pro zvolená vozidla a období (stejně jako zbytek statistik)."""
from collections import defaultdict
from decimal import Decimal

from services import places
from services.stats_service import StatsService

ZERO = Decimal("0")


def _year_bucket():
    return {"fuel": ZERO, "service": ZERO, "expense": ZERO, "rental": ZERO, "km": 0, "fuel_count": 0,
            "volume_l": ZERO, "priced_volume": ZERO, "priced_cost": ZERO}


def insights(session, vehicles, date_from=None, date_to=None):
    ids = [v.id for v in vehicles]
    result = {"by_year": [], "costs": [], "service_types": [], "places": {}, "fuel": None, "total": ZERO}
    if not ids:
        return result
    stats = StatsService(session)
    _, fuel, services, expenses = stats._load(ids, date_from, date_to)
    rentals = stats._load_rentals(ids, date_from, date_to)

    # --- po letech ---
    years = defaultdict(_year_bucket)
    for f in fuel:
        y = years[f.refuel_datetime.year]
        y["fuel"] += f.price_local or ZERO
        y["fuel_count"] += 1
        if f.unit == "l" and f.volume_liters:
            y["volume_l"] += f.volume_liters
            if f.price_local is not None:
                y["priced_volume"] += f.volume_liters
                y["priced_cost"] += f.price_local
    for s in services:
        years[s.service_date.year]["service"] += s.own_cost or ZERO
    for e in expenses:
        years[e.expense_date.year]["expense"] += e.own_cost or ZERO
    for r in rentals:
        years[r.date_from.year]["rental"] += r.price_local or ZERO
    for v in vehicles:
        charts = stats.odometer_charts(v.id, date_from, date_to)
        for label, km in zip(charts["yearly_km_labels"], charts["yearly_km"]):
            years[int(label)]["km"] += km
    by_year = []
    for year, y in sorted(years.items(), reverse=True):
        total = y["fuel"] + y["service"] + y["expense"] + y["rental"]
        by_year.append({
            "year": year, "km": y["km"], "fuel": y["fuel"], "service": y["service"], "expense": y["expense"],
            "rental": y["rental"], "total": total, "fuel_count": y["fuel_count"], "volume_l": y["volume_l"],
            "cost_per_km": (total / y["km"]) if y["km"] else None,
            "avg_price_l": (y["priced_cost"] / y["priced_volume"]) if y["priced_volume"] else None,
        })
    result["by_year"] = by_year
    result["max_year_total"] = max((y["total"] for y in by_year), default=ZERO)

    # --- kam jdou peníze: palivo, servis podle typu, výdaje podle kategorie, půjčovné ---
    service_types = defaultdict(lambda: {"count": 0, "cost": ZERO})
    for s in services:
        types = s.types or [s.service_type]
        share = (s.own_cost or ZERO) / len(types)
        for t in types:
            service_types[t]["count"] += 1
            service_types[t]["cost"] += share
    result["service_types"] = sorted(({"name": k, **v} for k, v in service_types.items()),
                                     key=lambda x: (-x["cost"], -x["count"], x["name"].lower()))
    categories = defaultdict(lambda: ZERO)
    for e in expenses:
        categories[e.category] += e.own_cost or ZERO
    fuel_cost = sum((f.price_local or ZERO for f in fuel), ZERO)
    service_cost = sum((s.own_cost or ZERO for s in services), ZERO)
    rental_cost = sum((r.price_local or ZERO for r in rentals), ZERO)
    costs = [("Palivo", fuel_cost, "fuel"), ("Servis", service_cost, "service")]
    costs += [(name, amount, "expense") for name, amount in sorted(categories.items(), key=lambda kv: -kv[1])]
    if rental_cost:
        costs.append(("Půjčovné", rental_cost, "key"))
    total = fuel_cost + service_cost + sum(categories.values(), ZERO) + rental_cost
    result["costs"] = [{"name": n, "amount": a, "icon": i, "share": (a / total * 100) if total else 0}
                       for n, a, i in costs if a]
    result["total"] = total

    # --- nejčastější místa ---
    result["places"] = {kind: places.overview(session, kind, ids, date_from, date_to)[:5] for kind in places.KINDS}

    # --- tankování: průměry a rekordy (jen litry, ať se nemíchá kWh a kg) ---
    liters = [f for f in fuel if f.unit == "l"]
    priced = [f for f in liters if f.unit_price_local]
    with_consumption = [f for f in liters if f.consumption]
    if liters:
        result["fuel"] = {
            "count": len(liters),
            "avg_volume": sum((f.volume_liters for f in liters), ZERO) / len(liters),
            "avg_cost": (sum((f.price_local or ZERO for f in liters), ZERO) / len(liters)),
            "cheapest": min(priced, key=lambda f: f.unit_price_local) if priced else None,
            "priciest": max(priced, key=lambda f: f.unit_price_local) if priced else None,
            "biggest": max(liters, key=lambda f: f.volume_liters),
            "best": min(with_consumption, key=lambda f: f.consumption) if with_consumption else None,
            "worst": max(with_consumption, key=lambda f: f.consumption) if with_consumption else None,
        }
    return result


def year_overview(session, vehicles, year_start, today):
    """Hlavní čísla letošního roku pro výchozí obrazovku."""
    summary = StatsService(session).fleet_summary(vehicles, year_start, today)
    return {"total_cost": summary["total_cost"], "distance": summary["distance"],
            "cost_per_km": summary["cost_per_km"], "fuel_count": summary["fuel_count"],
            "fuel_cost": summary["fuel_cost"]}
