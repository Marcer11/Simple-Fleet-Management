from collections import defaultdict, OrderedDict
from datetime import date
from decimal import Decimal

from models import FuelRecord, ServiceRecord, Expense, VehicleRental, Vehicle, VehicleNote, TireSwap, TireTreadCheck
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

    def _load_rentals(self, vehicle_ids, date_from=None, date_to=None):
        """Půjčení vozidel začínající v období (půjčovné se počítá ke dni půjčení)."""
        if not vehicle_ids:
            return []
        query = self.session.query(VehicleRental).filter(VehicleRental.vehicle_id.in_(vehicle_ids))
        if date_from:
            query = query.filter(VehicleRental.date_from >= date_from)
        if date_to:
            query = query.filter(VehicleRental.date_from <= date_to)
        return query.all()

    def vehicle_summary(self, vehicle_id, date_from=None, date_to=None):
        """Souhrnné ukazatele + data pro grafy jednoho vozidla."""
        all_fuel, fuel, services, expenses = self._load([vehicle_id], date_from, date_to)
        rentals = self._load_rentals([vehicle_id], date_from, date_to)

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
        rental_cost = sum((r.price_local or ZERO for r in rentals), ZERO)
        total_cost = fuel_cost + service_cost + expense_cost + rental_cost

        # --- ujetá vzdálenost v období ---
        odometers = [f.odometer for f in fuel] + [s.odometer for s in services if s.odometer is not None] \
            + [e.odometer for e in expenses if e.odometer is not None] \
            + [km for r in rentals for km in (r.odometer_from, r.odometer_to) if km is not None]
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
            "rental_cost": rental_cost,
            "rental_count": len(rentals),
            "total_cost": total_cost,
            "distance": distance,
            "cost_per_km": (total_cost / distance) if distance else None,
            "fuel_cost_per_km": (fuel_cost / distance) if distance else None,
            "avg_consumption": avg_consumption,
            "volume_by_type": dict(volume_by_type),
            "expense_by_category": dict(sorted(expense_by_category.items(), key=lambda kv: -kv[1])),
            "charts": {**self._charts(fuel, services, expenses, segments, date_from, date_to, rentals),
                       **self.odometer_charts(vehicle_id, date_from, date_to)},
        }

    def odometer_readings(self, vehicle_id):
        """Všechny známé stavy tachometru vozidla: [(datum, km)] seřazené, nejvyšší stav za den."""
        q = self.session.query
        items = [(at.date(), km) for at, km in q(FuelRecord.refuel_datetime, FuelRecord.odometer)
                 .filter(FuelRecord.vehicle_id == vehicle_id)]
        items += [(at.date(), km) for at, km in q(VehicleNote.note_datetime, VehicleNote.odometer)
                  .filter(VehicleNote.vehicle_id == vehicle_id)]
        for column, km_column, model in ((ServiceRecord.service_date, ServiceRecord.odometer, ServiceRecord),
                                         (Expense.expense_date, Expense.odometer, Expense),
                                         (TireSwap.swap_date, TireSwap.odometer, TireSwap),
                                         (TireTreadCheck.check_date, TireTreadCheck.odometer, TireTreadCheck)):
            items += list(q(column, km_column).filter(model.vehicle_id == vehicle_id))
        rentals = q(VehicleRental.date_from, VehicleRental.odometer_from, VehicleRental.date_to,
                    VehicleRental.odometer_to).filter(VehicleRental.vehicle_id == vehicle_id)
        for d_from, km_from, d_to, km_to in rentals:
            items += [(d_from, km_from), (d_to, km_to)]
        vehicle = self.session.get(Vehicle, vehicle_id)
        if vehicle is not None:
            items += [(day, km) for day, (km, _) in self.odometer_marks(vehicle).items()]
        by_day = {}
        for day, km in items:
            if day is not None and km is not None:
                by_day[day] = max(km, by_day.get(day, 0))
        result, running = [], None
        for day, km in sorted(by_day.items()):
            running = km if running is None else max(running, km)  # chybný starší zápis nesmí jít dolů
            result.append((day, running))
        return result

    @staticmethod
    def odometer_marks(vehicle):
        """Nákup a prodej jako body grafu: {datum: (km, popis)}.

        Bod vznikne jen při vyplněném datu i stavu tachometru - 0 km je platný stav (nové vozidlo),
        prázdné pole (None) znamená, že stav neznáme.
        """
        marks = {}
        for day, km, label in ((vehicle.purchase_date, vehicle.purchase_odometer, "Nákup vozidla"),
                               (vehicle.sale_date, vehicle.sale_odometer, "Prodej vozidla")):
            if day is not None and km is not None:
                marks[day] = (km, label)
        return marks

    def _odometer_points(self, vehicle_id, date_from=None, date_to=None):
        """Body grafu kilometrů ve zvoleném období (s popiskem u nákupu a prodeje)."""
        vehicle = self.session.get(Vehicle, vehicle_id)
        marks = self.odometer_marks(vehicle) if vehicle is not None else {}
        points = []
        for d, km in self.odometer_readings(vehicle_id):
            if (date_from is None or d >= date_from) and (date_to is None or d <= date_to):
                point = {"x": d.isoformat(), "y": km}
                if d in marks:
                    point["label"] = marks[d][1]
                points.append(point)
        return points

    def odometer_charts(self, vehicle_id, date_from=None, date_to=None):
        """Stav tachometru v čase a najeto po měsících (lineárně mezi zápisy)."""
        readings = self.odometer_readings(vehicle_id)
        points = self._odometer_points(vehicle_id, date_from, date_to)
        labels, values = [], []
        if len(readings) >= 2:
            first, last = readings[0][0], readings[-1][0]
            start = max(first, date_from) if date_from else first
            end = min(last, date_to) if date_to else last
            if (end.year - start.year) * 12 + end.month - start.month > 35:
                start = add_months(date(end.year, end.month, 1), -35)
            for key in _months_range(start, end) if start <= end else []:
                month_start = date(int(key[:4]), int(key[5:]), 1)
                month_end = add_months(month_start, 1)
                km = self._odometer_at(readings, min(month_end, last)) - self._odometer_at(readings, max(month_start, first))
                labels.append(key)
                values.append(max(round(km), 0))
        return {"odometer": points, "monthly_km_labels": labels, "monthly_km": values}

    @staticmethod
    def _odometer_at(readings, day):
        """Stav tachometru k danému dni - lineární interpolace mezi zápisy."""
        prev = readings[0]
        for d, km in readings:
            if d >= day:
                if d == prev[0]:
                    return km
                return prev[1] + (km - prev[1]) * (day - prev[0]).days / (d - prev[0]).days
            prev = (d, km)
        return readings[-1][1]

    def _charts(self, fuel, services, expenses, segments, date_from, date_to, rentals=()):
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
            + [e.expense_date for e in expenses] + [r.date_from for r in rentals]
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
                monthly[key] = {"fuel": 0.0, "service": 0.0, "expense": 0.0, "rental": 0.0}
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
            for r in rentals:
                key = _month_key(r.date_from)
                if key in monthly:
                    monthly[key]["rental"] += float(r.price_local or 0)

        return {
            "consumption": dict(consumption_series),
            "unit_price": price_series,
            "monthly_labels": list(monthly.keys()),
            "monthly_fuel": [round(v["fuel"], 2) for v in monthly.values()],
            "monthly_service": [round(v["service"], 2) for v in monthly.values()],
            "monthly_expense": [round(v["expense"], 2) for v in monthly.values()],
            "monthly_rental": [round(v["rental"], 2) for v in monthly.values()],
        }

    def year_costs(self, vehicle_ids, year):
        """Náklady za rok v CZK podle vozidla: {vehicle_id: Decimal}."""
        start, end = date(year, 1, 1), date(year, 12, 31)
        totals = defaultdict(lambda: ZERO)
        if not vehicle_ids:
            return totals
        _, fuel, services, expenses = self._load(vehicle_ids, start, end)
        for item in fuel + services + expenses + self._load_rentals(vehicle_ids, start, end):
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
        empty = {"rows": [], "fuel_cost": ZERO, "service_cost": ZERO, "expense_cost": ZERO, "rental_cost": ZERO,
                 "total_cost": ZERO, "distance": 0, "cost_per_km": None, "fuel_count": 0,
                 "charts": {"monthly_labels": [], "monthly_fuel": [], "monthly_service": [],
                            "monthly_expense": [], "monthly_rental": [], "unit_price": {}, "odometer": {},
                            "odometer_rental": []}}
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
        rental_cost = sum((r["rental_cost"] for r in rows), ZERO)
        total_cost = fuel_cost + service_cost + expense_cost + rental_cost
        distance = sum(r["distance"] or 0 for r in rows)
        # náklady na km jen z vozidel, u kterých známe ujetou vzdálenost
        cost_with_distance = sum((r["total_cost"] for r in rows if r["distance"]), ZERO)

        charts = self._charts(fuel, services, expenses, [], date_from, date_to,
                              self._load_rentals(ids, date_from, date_to))
        charts.pop("consumption", None)
        names = self._vehicle_names(vehicles)
        charts["unit_price"] = self._price_points(fuel, names)
        charts["odometer"] = self._distance_series(vehicles, date_from, date_to)
        # řady půjčených vozidel - v grafu kilometrů je lze skrýt
        charts["odometer_rental"] = [names[v.id] for v in vehicles
                                     if v.is_rental and names[v.id] in charts["odometer"]]
        return {
            "rows": rows,
            "fuel_count": len(fuel),
            "fuel_cost": fuel_cost,
            "service_cost": service_cost,
            "expense_cost": expense_cost,
            "rental_cost": rental_cost,
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

    def _distance_series(self, vehicles, date_from=None, date_to=None):
        """Kilometry každého vozidla v období: y = ujeto od prvního bodu, odo = skutečný stav.

        Vozidla mají tachometry v úplně jiných řádech (0 vs. 400 000 km) - společný začátek
        v nule je dělá porovnatelnými; graf lze přepnout i na skutečný stav tachometru.
        Body jsou ze všech záznamů se stavem tachometru včetně nákupu a prodeje vozidla.
        """
        names = self._vehicle_names(vehicles)
        result = {}
        for v in vehicles:
            points = self._odometer_points(v.id, date_from, date_to)
            if not points:
                continue
            base = points[0]["y"]
            result[names[v.id]] = [{**p, "y": p["y"] - base, "odo": p["y"]} for p in points]
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
