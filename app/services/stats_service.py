from collections import defaultdict, OrderedDict
from datetime import date
from decimal import Decimal

from models import FuelRecord, ServiceRecord, Expense
from models.fuel_record import fuel_unit
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
            key = seg["record"].fuel_type
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
            consumption_series[record.fuel_type].append({
                "x": record.refuel_datetime.strftime("%Y-%m-%d"),
                "y": float(seg["consumption"]),
            })

        # Cena za jednotku v čase
        price_series = defaultdict(list)
        for record in sorted(fuel, key=lambda r: r.refuel_datetime):
            if record.unit_price_local is not None:
                price_series[record.fuel_type].append({
                    "x": record.refuel_datetime.strftime("%Y-%m-%d"),
                    "y": float(record.unit_price_local),
                })

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
            "unit_price": dict(price_series),
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
            totals[seg["record"].fuel_type]["volume"] += seg["volume"]
            totals[seg["record"].fuel_type]["distance"] += seg["distance"]
        return {
            fuel_type: {"value": v["volume"] / v["distance"] * 100, "unit": fuel_unit(fuel_type)}
            for fuel_type, v in totals.items() if v["distance"]
        }

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
                rows.append({"vehicle": vehicle, **summary})

        fuel_cost = sum((r["fuel_cost"] for r in rows), ZERO)
        service_cost = sum((r["service_cost"] for r in rows), ZERO)
        expense_cost = sum((r["expense_cost"] for r in rows), ZERO)
        total_cost = fuel_cost + service_cost + expense_cost
        distance = sum(r["distance"] or 0 for r in rows)
        # náklady na km jen z vozidel, u kterých známe ujetou vzdálenost
        cost_with_distance = sum((r["total_cost"] for r in rows if r["distance"]), ZERO)

        charts = self._charts(fuel, services, expenses, [], date_from, date_to)
        charts.pop("consumption", None)
        charts["unit_price"] = self._monthly_unit_price(fuel)
        charts["odometer"] = self._odometer_series(vehicles, fuel, services, expenses)
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
    def _monthly_unit_price(fuel):
        """Průměrná cena za jednotku po měsících a druzích paliva (vážená množstvím)."""
        sums = defaultdict(lambda: defaultdict(lambda: [ZERO, ZERO]))  # typ -> měsíc -> [cena, množství]
        for f in fuel:
            if f.price_local is None or not f.volume_liters:
                continue
            bucket = sums[f.fuel_type][_month_key(f.refuel_datetime)]
            bucket[0] += f.price_local
            bucket[1] += f.volume_liters
        return {
            fuel_type: [{"x": month, "y": round(float(price / volume), 2)}
                        for month, (price, volume) in sorted(months.items()) if volume]
            for fuel_type, months in sorted(sums.items())
        }

    @staticmethod
    def _odometer_series(vehicles, fuel, services, expenses):
        """Stav tachometru v čase pro každé vozidlo (nejvyšší hodnota daného dne)."""
        points = defaultdict(dict)  # vehicle_id -> {datum: km}
        items = [(f.vehicle_id, f.refuel_datetime.date(), f.odometer) for f in fuel] \
            + [(s.vehicle_id, s.service_date, s.odometer) for s in services] \
            + [(e.vehicle_id, e.expense_date, e.odometer) for e in expenses]
        for vehicle_id, day, km in items:
            if km is None:
                continue
            key = day.isoformat()
            points[vehicle_id][key] = max(km, points[vehicle_id].get(key, 0))

        names = {}
        for v in vehicles:
            name = v.display_name
            names[v.id] = f"{name} ({v.license_plate or v.id})" if name in names.values() else name
        return {names[v.id]: [{"x": day, "y": km} for day, km in sorted(points[v.id].items())]
                for v in vehicles if points.get(v.id)}
