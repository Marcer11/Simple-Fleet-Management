from collections import defaultdict, OrderedDict
from datetime import date
from decimal import Decimal

from models import FuelRecord, ServiceRecord, Expense
from models.fuel_record import FUEL_CATEGORIES, fuel_unit
from services.fuel_record_service import compute_consumption_segments
from services.maintenance_service import add_months

ZERO = Decimal("0")


def _month_key(d):
    return f"{d.year}-{d.month:02d}"


def _months_range(start, end):
    """Seznam klíčů měsíců 'YYYY-MM' od start do end včetně."""
    keys = []
    current = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while current <= last:
        keys.append(_month_key(current))
        current = add_months(current, 1)
    return keys


class StatsService:
    def __init__(self, session):
        self.session = session

    def _load(self, vehicle_ids, date_from=None, date_to=None):
        fuel = self.session.query(FuelRecord).filter(FuelRecord.vehicle_id.in_(vehicle_ids)).all()
        services = self.session.query(ServiceRecord).filter(ServiceRecord.vehicle_id.in_(vehicle_ids)).all()
        expenses = self.session.query(Expense).filter(Expense.vehicle_id.in_(vehicle_ids)).all()

        def in_range(d):
            return (date_from is None or d >= date_from) and (date_to is None or d <= date_to)

        return (
            fuel,
            [f for f in fuel if in_range(f.refuel_datetime.date())],
            [s for s in services if in_range(s.service_date)],
            [e for e in expenses if in_range(e.expense_date)],
        )

    def vehicle_summary(self, vehicle_id, date_from=None, date_to=None):
        """Souhrnné ukazatele + data pro grafy jednoho vozidla."""
        all_fuel, fuel, services, expenses = self._load([vehicle_id], date_from, date_to)

        # --- spotřeba (počítáno ze všech záznamů, filtrováno podle data) ---
        segments = [s for s in compute_consumption_segments(all_fuel)
                    if (date_from is None or s["record"].refuel_datetime.date() >= date_from)
                    and (date_to is None or s["record"].refuel_datetime.date() <= date_to)]
        consumption_by_type = defaultdict(lambda: {"volume": ZERO, "distance": 0})
        for seg in segments:
            key = seg["record"].fuel_group
            consumption_by_type[key]["volume"] += seg["volume"]
            consumption_by_type[key]["distance"] += seg["distance"]
        avg_consumption = {
            fuel_type: {
                "value": (v["volume"] / v["distance"] * 100) if v["distance"] else None,
                "unit": fuel_unit(fuel_type),
            }
            for fuel_type, v in consumption_by_type.items()
        }

        # --- náklady ---
        fuel_cost = sum((f.price_local or ZERO for f in fuel), ZERO)
        service_cost = sum((s.price_local or ZERO for s in services), ZERO)
        expense_cost = sum((e.price_local or ZERO for e in expenses), ZERO)
        total_cost = fuel_cost + service_cost + expense_cost

        # --- ujetá vzdálenost v období ---
        odometers = [f.odometer for f in fuel] + [s.odometer for s in services if s.odometer] \
            + [e.odometer for e in expenses if e.odometer]
        distance = (max(odometers) - min(odometers)) if len(odometers) >= 2 else None

        volume_by_type = defaultdict(lambda: ZERO)
        for f in fuel:
            volume_by_type[f.fuel_type] += f.volume_liters or ZERO

        expense_by_category = defaultdict(lambda: ZERO)
        for e in expenses:
            expense_by_category[e.category] += e.price_local or ZERO

        return {
            "fuel_count": len(fuel),
            "fuel_cost": fuel_cost,
            "service_cost": service_cost,
            "expense_cost": expense_cost,
            "total_cost": total_cost,
            "distance": distance,
            "cost_per_km": (total_cost / distance) if distance else None,
            "fuel_cost_per_km": (fuel_cost / distance) if distance else None,
            "avg_consumption": avg_consumption,
            "volume_by_type": dict(volume_by_type),
            "expense_by_category": dict(sorted(expense_by_category.items(), key=lambda kv: -kv[1])),
            "charts": self._charts(fuel, services, expenses, segments, date_from, date_to),
        }

    def _charts(self, fuel, services, expenses, segments, date_from, date_to):
        # Spotřeba v čase (body podle data tankování)
        consumption_series = defaultdict(list)
        for seg in sorted(segments, key=lambda s: s["record"].refuel_datetime):
            record = seg["record"]
            consumption_series[record.fuel_group].append({
                "x": record.refuel_datetime.strftime("%Y-%m-%d"),
                "y": float(seg["consumption"]),
                "group": record.fuel_group,
            })

        # Cena za jednotku u každého tankování
        price_series = self._price_points(fuel)

        # Měsíční náklady podle kategorie
        dates = [f.refuel_datetime.date() for f in fuel] + [s.service_date for s in services] \
            + [e.expense_date for e in expenses]
        monthly = OrderedDict()
        if dates:
            start = date_from or min(dates)
            end = date_to or max(max(dates), date.today())
            if end < start:
                end = start
            # Omezíme na posledních 36 měsíců, aby graf zůstal čitelný
            if (end.year - start.year) * 12 + end.month - start.month > 36:
                start = add_months(date(end.year, end.month, 1), -35)
            for key in _months_range(start, end):
                monthly[key] = {"fuel": 0.0, "service": 0.0, "expense": 0.0}
            for f in fuel:
                key = _month_key(f.refuel_datetime)
                if key in monthly:
                    monthly[key]["fuel"] += float(f.price_local or 0)
            for s in services:
                key = _month_key(s.service_date)
                if key in monthly:
                    monthly[key]["service"] += float(s.price_local or 0)
            for e in expenses:
                key = _month_key(e.expense_date)
                if key in monthly:
                    monthly[key]["expense"] += float(e.price_local or 0)

        return {
            "consumption": dict(consumption_series),
            "unit_price": price_series,
            "monthly_labels": list(monthly.keys()),
            "monthly_fuel": [round(v["fuel"], 2) for v in monthly.values()],
            "monthly_service": [round(v["service"], 2) for v in monthly.values()],
            "monthly_expense": [round(v["expense"], 2) for v in monthly.values()],
        }

    def year_costs(self, vehicle_ids, year):
        """Náklady za rok v CZK podle vozidla: {vehicle_id: Decimal}."""
        start, end = date(year, 1, 1), date(year, 12, 31)
        totals = defaultdict(lambda: ZERO)
        if not vehicle_ids:
            return totals
        _, fuel, services, expenses = self._load(vehicle_ids, start, end)
        for item in fuel + services + expenses:
            totals[item.vehicle_id] += item.price_local or ZERO
        return totals

    def avg_consumption(self, vehicle_id):
        """Průměrná spotřeba za celé období podle typu paliva."""
        records = self.session.query(FuelRecord).filter(FuelRecord.vehicle_id == vehicle_id).all()
        totals = defaultdict(lambda: {"volume": ZERO, "distance": 0})
        for seg in compute_consumption_segments(records):
            totals[seg["record"].fuel_group]["volume"] += seg["volume"]
            totals[seg["record"].fuel_group]["distance"] += seg["distance"]
        return {
            fuel_type: {"value": v["volume"] / v["distance"] * 100, "unit": fuel_unit(fuel_type)}
            for fuel_type, v in totals.items() if v["distance"]
        }

    def fuel_breakdown(self, vehicle_id, date_from=None, date_to=None):
        """Spotřeba a natankované množství podle druhu paliva a v něm podle konkrétního paliva.

        Druh (Benzín, LPG…) je řada "plná–plná" - Natural 95 a 98 se počítají dohromady, benzín
        a LPG (nebo nafta a AdBlue) zvlášť. Spotřeba konkrétního paliva = úseky, které jím byly
        uzavřeny (natankováno do plna). Seřazeno podle množství - hlavní palivo první.
        """
        records = self.session.query(FuelRecord).filter(FuelRecord.vehicle_id == vehicle_id).all()

        def in_range(record):
            d = record.refuel_datetime.date()
            return (date_from is None or d >= date_from) and (date_to is None or d <= date_to)

        def bucket():
            return {"volume": ZERO, "count": 0, "seg_volume": ZERO, "seg_distance": 0}

        groups = defaultdict(lambda: {**bucket(), "fuels": defaultdict(bucket)})
        for r in records:
            if not in_range(r):
                continue
            group = groups[r.fuel_group]
            fuel = group["fuels"][(r.fuel_type or "").strip()]
            for b in (group, fuel):
                b["volume"] += r.volume_liters or ZERO
                b["count"] += 1
        for seg in compute_consumption_segments(records):
            r = seg["record"]
            if not in_range(r):
                continue
            group = groups[r.fuel_group]
            for b in (group, group["fuels"][(r.fuel_type or "").strip()]):
                b["seg_volume"] += seg["volume"]
                b["seg_distance"] += seg["distance"]

        def finish(name, b):
            return {"name": name, "volume": b["volume"], "count": b["count"],
                    "consumption": (b["seg_volume"] / b["seg_distance"] * 100) if b["seg_distance"] else None}

        result = []
        for name, g in groups.items():
            fuels = sorted((finish(n, f) for n, f in g["fuels"].items()), key=lambda f: (-f["volume"], f["name"]))
            result.append({**finish(name, g), "unit": fuel_unit(name), "fuels": fuels,
                           "is_fuel": name in FUEL_CATEGORIES,  # AdBlue apod. není pohonná hmota
                           "show_fuels": len(fuels) > 1 or fuels[0]["name"].lower() != name.lower()})
        result.sort(key=lambda g: (not g["is_fuel"], -g["volume"], g["name"]))
        fuels = [g for g in result if g["is_fuel"]]
        for g in result:
            g["role"] = None
            if g["is_fuel"] and len(fuels) > 1:
                g["role"] = "hlavní" if g is fuels[0] else "alternativní"
        return result

    # ------------------------------------------------------------------
    # Statistiky celého vozového parku
    # ------------------------------------------------------------------

    def fleet_summary(self, vehicles, date_from=None, date_to=None):
        """Souhrn za všechna zadaná vozidla: řádky po vozidlech, součty a data grafů."""
        vehicles = sorted(vehicles, key=lambda v: v.id)  # stálé pořadí = stálé barvy v grafech
        ids = [v.id for v in vehicles]
        empty = {"rows": [], "fuel_cost": ZERO, "service_cost": ZERO, "expense_cost": ZERO,
                 "total_cost": ZERO, "distance": 0, "cost_per_km": None, "fuel_count": 0,
                 "charts": {"monthly_labels": [], "monthly_fuel": [], "monthly_service": [],
                            "monthly_expense": [], "unit_price": {}, "odometer": {}}}
        if not ids:
            return empty

        _, fuel, services, expenses = self._load(ids, date_from, date_to)
        rows = []
        for vehicle in vehicles:
            summary = self.vehicle_summary(vehicle.id, date_from, date_to)
            if summary["total_cost"] or summary["distance"] or summary["fuel_count"]:
                rows.append({"vehicle": vehicle, **summary, "profile": self.usage_profile(vehicle.id)})

        fuel_cost = sum((r["fuel_cost"] for r in rows), ZERO)
        service_cost = sum((r["service_cost"] for r in rows), ZERO)
        expense_cost = sum((r["expense_cost"] for r in rows), ZERO)
        total_cost = fuel_cost + service_cost + expense_cost
        distance = sum(r["distance"] or 0 for r in rows)
        # náklady na km jen z vozidel, u kterých známe ujetou vzdálenost
        cost_with_distance = sum((r["total_cost"] for r in rows if r["distance"]), ZERO)

        charts = self._charts(fuel, services, expenses, [], date_from, date_to)
        charts.pop("consumption", None)
        charts["unit_price"] = self._price_points(fuel, self._vehicle_names(vehicles))
        charts["odometer"] = self._distance_series(vehicles, fuel, services, expenses)
        return {
            "rows": rows,
            "fuel_count": len(fuel),
            "fuel_cost": fuel_cost,
            "service_cost": service_cost,
            "expense_cost": expense_cost,
            "total_cost": total_cost,
            "distance": distance,
            "cost_per_km": (cost_with_distance / distance) if distance else None,
            "charts": charts,
        }

    @staticmethod
    def _vehicle_names(vehicles):
        names = {}
        for v in vehicles:
            name = v.display_name
            names[v.id] = f"{name} ({v.license_plate or v.id})" if name in names.values() else name
        return names

    @staticmethod
    def _price_points(fuel, vehicle_names=None):
        """Cena za jednotku (Kč) u každého tankování, řady podle paliva."""
        series = defaultdict(list)
        for f in sorted(fuel, key=lambda r: (r.refuel_datetime, r.id or 0)):
            if f.unit_price_local is None:
                continue
            point = {"x": f.refuel_datetime.strftime("%Y-%m-%dT%H:%M"), "y": round(float(f.unit_price_local), 3),
                     "unit": f.unit}
            if f.station_name:
                point["station"] = f.station_name
            if vehicle_names:
                point["vehicle"] = vehicle_names.get(f.vehicle_id)
            series[(f.fuel_type or "").strip()].append(point)
        return dict(sorted(series.items()))

    @classmethod
    def _distance_series(cls, vehicles, fuel, services, expenses):
        """Ujeto od prvního záznamu v období pro každé vozidlo (nejvyšší stav daného dne).

        Vozidla mají tachometry v úplně jiných řádech (0 vs. 400 000 km) - společný začátek
        v nule je dělá porovnatelnými; skutečný stav je v bodu jako "odo".
        """
        points = defaultdict(dict)  # vehicle_id -> {datum: km}
        items = [(f.vehicle_id, f.refuel_datetime.date(), f.odometer) for f in fuel]             + [(s.vehicle_id, s.service_date, s.odometer) for s in services]             + [(e.vehicle_id, e.expense_date, e.odometer) for e in expenses]
        for vehicle_id, day, km in items:
            if km is None:
                continue
            key = day.isoformat()
            points[vehicle_id][key] = max(km, points[vehicle_id].get(key, 0))

        names = cls._vehicle_names(vehicles)
        result = {}
        for v in vehicles:
            days = sorted(points.get(v.id, {}).items())
            if not days:
                continue
            base = days[0][1]
            running = base
            series = []
            for day, km in days:
                running = max(running, km)  # chybný starší zápis nesmí jít pod nulu
                series.append({"x": day, "y": running - base, "odo": running})
            result[names[v.id]] = series
        return result

    def usage_profile(self, vehicle_id):
        """Jak často se tankuje a kolik se průměrně najezdí (z celé historie vozidla)."""
        fuel = (self.session.query(FuelRecord.refuel_datetime, FuelRecord.odometer)
                .filter(FuelRecord.vehicle_id == vehicle_id).order_by(FuelRecord.refuel_datetime).all())
        readings = [(r.refuel_datetime.date(), r.odometer) for r in fuel]
        readings += [(d, km) for d, km in self.session.query(ServiceRecord.service_date, ServiceRecord.odometer)
                     .filter(ServiceRecord.vehicle_id == vehicle_id, ServiceRecord.odometer.isnot(None))]
        readings += [(d, km) for d, km in self.session.query(Expense.expense_date, Expense.odometer)
                     .filter(Expense.vehicle_id == vehicle_id, Expense.odometer.isnot(None))]
        profile = {"refuel_count": len(fuel), "days_between": None, "per_month": None,
                   "km_between": None, "km_per_year": None}
        if len(fuel) >= 2:
            span = (fuel[-1].refuel_datetime - fuel[0].refuel_datetime).total_seconds() / 86400
            if span >= 1:
                profile["days_between"] = span / (len(fuel) - 1)
                profile["per_month"] = 30.44 / profile["days_between"]
            km = fuel[-1].odometer - fuel[0].odometer
            if km > 0:
                profile["km_between"] = km / (len(fuel) - 1)
        if len(readings) >= 2:
            first, last = min(readings), max(readings)
            days = (last[0] - first[0]).days
            km = max(km for _, km in readings) - min(km for _, km in readings)
            if days >= 30 and km > 0:  # z kratšího období by roční odhad byl nesmyslný
                profile["km_per_year"] = km / days * 365.25
        return profile
