from datetime import datetime, time, timedelta
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from models import FuelRecord, Vehicle
from models.fuel_record import FUEL_CATEGORIES, guess_fuel_category
from services.errors import ValidationError, NotFoundError
from services.pricing import to_decimal, normalize_currency, Q2, Q3

FUEL_RECORD_FIELDS = (
    "vehicle_id", "refuel_datetime", "odometer", "fuel_type", "volume_liters", "unit_price",
    "price_paid", "currency_code", "unit_price_local", "price_local", "payment_method",
    "station_name", "station_address", "full_tank", "skipped_refuel", "note", "fuel_category",
)


def _fuel_key(fuel_type):
    return (fuel_type or "").strip().lower()


def compute_consumption_segments(records):
    """
    Výpočet spotřeby metodou "plná - plná".

    Spotřeba se počítá u tankování s plnou nádrží: objem všech tankování od předchozí
    plné nádrže (včetně aktuálního) / ujetá vzdálenost * 100. Pokud je u některého
    tankování v úseku příznak "vynechané tankování", úsek se nepočítá.
    Každý druh paliva má vlastní řadu (např. LPG a benzín u bi-fuel vozidel); Natural 95
    a Verva 100 jsou obojí benzín (FuelRecord.fuel_group).

    Vrací seznam dictů {record, volume, distance, consumption} pro spočtené úseky.
    """
    by_type = defaultdict(list)
    for record in sorted(records, key=lambda r: (r.refuel_datetime, r.odometer, r.id or 0)):
        by_type[_fuel_key(record.fuel_group)].append(record)

    segments = []
    for series in by_type.values():
        last_full = None
        volume = Decimal("0")
        broken = False
        for record in series:
            if last_full is None:
                if record.full_tank:
                    last_full, volume, broken = record, Decimal("0"), False
                continue

            volume += Decimal(str(record.volume_liters))
            if record.skipped_refuel:
                broken = True
            if record.full_tank:
                distance = record.odometer - last_full.odometer
                if not broken and distance > 0:
                    consumption = (volume / distance * 100).quantize(Q2, rounding=ROUND_HALF_UP)
                    if consumption < 1000:  # DECIMAL(5,2)
                        segments.append({
                            "record": record, "volume": volume,
                            "distance": distance, "consumption": consumption,
                        })
                last_full, volume, broken = record, Decimal("0"), False
    return segments


class FuelRecordService:
    def __init__(self, session):
        self.session = session

    # ------------------------------------------------------------------
    # Čtení
    # ------------------------------------------------------------------

    def get_all_fuel_records(self):
        return self.session.query(FuelRecord).order_by(FuelRecord.refuel_datetime.desc()).all()

    def get_fuel_records_for_vehicle(self, vehicle_id):
        return (
            self.session.query(FuelRecord)
            .filter(FuelRecord.vehicle_id == vehicle_id)
            .order_by(FuelRecord.refuel_datetime.desc())
            .all()
        )

    def get_fuel_record(self, record_id):
        return self.session.get(FuelRecord, record_id)

    def search(self, vehicle_ids, date_from=None, date_to=None, fuel_type=None, limit=None):
        """Tankování pro dané vozidla s volitelným filtrem (date_from/date_to jsou date)."""
        if not vehicle_ids:
            return []
        query = self.session.query(FuelRecord).filter(FuelRecord.vehicle_id.in_(vehicle_ids))
        # Rozsah [date_from 00:00, date_to + 1 den 00:00) - vždy jako datetime, aby databáze
        # neporovnávala DATETIME s DATE (MySQL/MariaDB to dělají různě)
        if date_from:
            query = query.filter(FuelRecord.refuel_datetime >= datetime.combine(date_from, time.min))
        if date_to:
            query = query.filter(FuelRecord.refuel_datetime
                                 < datetime.combine(date_to + timedelta(days=1), time.min))
        if fuel_type:
            query = query.filter(FuelRecord.fuel_type == fuel_type)
        query = query.order_by(FuelRecord.refuel_datetime.desc(), FuelRecord.id.desc())
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_last_record(self, vehicle_id):
        return (self.session.query(FuelRecord)
                .filter(FuelRecord.vehicle_id == vehicle_id)
                .order_by(FuelRecord.refuel_datetime.desc())
                .first())

    def get_used_values(self, vehicle_ids, column):
        """Dříve použité hodnoty (např. čerpací stanice) pro našeptávání."""
        if not vehicle_ids:
            return []
        col = getattr(FuelRecord, column)
        rows = (self.session.query(col)
                .filter(FuelRecord.vehicle_id.in_(vehicle_ids), col.isnot(None))
                .distinct().limit(100).all())
        return sorted({r[0] for r in rows if r[0]})

    # ------------------------------------------------------------------
    # Zápis
    # ------------------------------------------------------------------

    def create_fuel_record(self, vehicle_id, refuel_datetime, odometer, fuel_type, volume_liters, unit_price,
                           price_paid, currency_code, unit_price_local, price_local, payment_method=None,
                           station_name=None, full_tank=False, skipped_refuel=False, consumption=None, note=None,
                           station_address=None, created_by_id=None, fuel_category=None):
        # Parametr consumption je zachován kvůli kompatibilitě - spotřeba se vždy dopočítá.
        data = self._validate({
            "vehicle_id": vehicle_id, "refuel_datetime": refuel_datetime, "odometer": odometer,
            "fuel_type": fuel_type, "volume_liters": volume_liters, "unit_price": unit_price,
            "price_paid": price_paid, "currency_code": currency_code,
            "unit_price_local": unit_price_local, "price_local": price_local,
            "payment_method": payment_method, "station_name": station_name,
            "station_address": station_address,
            "full_tank": full_tank, "skipped_refuel": skipped_refuel, "note": note,
            "fuel_category": fuel_category,
        })
        self._check_odometer(data["vehicle_id"], data["refuel_datetime"], data["odometer"])

        fuel_record = FuelRecord(**data, created_by_id=created_by_id)
        self.session.add(fuel_record)
        self.session.flush()
        self.recalculate_consumption(fuel_record.vehicle_id)
        self.session.commit()
        return fuel_record

    def update_fuel_record(self, record, data):
        current = {field: getattr(record, field) for field in FUEL_RECORD_FIELDS}
        if "fuel_type" in data and "fuel_category" not in data:
            current["fuel_category"] = None  # jiné palivo -> druh se odhadne znovu
        current.update(data)
        validated = self._validate(current)
        self._check_odometer(validated["vehicle_id"], validated["refuel_datetime"], validated["odometer"],
                             exclude_id=record.id)
        old_vehicle_id = record.vehicle_id
        for key, value in validated.items():
            setattr(record, key, value)
        self.session.flush()
        self.recalculate_consumption(record.vehicle_id)
        if old_vehicle_id != record.vehicle_id:
            self.recalculate_consumption(old_vehicle_id)
        self.session.commit()
        return record

    def delete_fuel_record(self, record):
        vehicle_id = record.vehicle_id
        self.session.delete(record)
        self.session.flush()
        self.recalculate_consumption(vehicle_id)
        self.session.commit()

    def recalculate_consumption(self, vehicle_id):
        """Přepočítá uloženou spotřebu u všech tankování vozidla (bez commitu)."""
        records = self.session.query(FuelRecord).filter(FuelRecord.vehicle_id == vehicle_id).all()
        computed = {seg["record"].id: seg["consumption"] for seg in compute_consumption_segments(records)}
        for record in records:
            record.consumption = computed.get(record.id)

    # ------------------------------------------------------------------
    # Validace
    # ------------------------------------------------------------------

    def _validate(self, data):
        errors = []

        if not data.get("vehicle_id"):
            errors.append("Vozidlo je povinné.")
        elif self.session.get(Vehicle, data["vehicle_id"]) is None:
            raise NotFoundError("Vozidlo nenalezeno.")

        if not data.get("refuel_datetime"):
            errors.append("Datum a čas tankování jsou povinné.")

        odometer = data.get("odometer")
        if odometer is None or odometer == "":
            errors.append("Stav tachometru je povinný.")
        else:
            data["odometer"] = int(odometer)
            if data["odometer"] < 0:
                errors.append("Stav tachometru nemůže být záporný.")

        data["fuel_type"] = (data.get("fuel_type") or "").strip()
        if not data["fuel_type"]:
            errors.append("Typ paliva je povinný.")
        elif len(data["fuel_type"]) > 30:
            errors.append("Typ paliva může mít nejvýše 30 znaků.")
        # druh: hodnota ze seznamu paliv uživatele; "" = vědomě bez druhu, None = odhad podle názvu
        category = data.get("fuel_category")
        if category == "":
            category = None
        elif category not in FUEL_CATEGORIES:
            category = guess_fuel_category(data["fuel_type"])
        data["fuel_category"] = category

        data["volume_liters"] = to_decimal(data.get("volume_liters"), Q2)
        if data["volume_liters"] is None or data["volume_liters"] <= 0:
            errors.append("Množství paliva musí být větší než nula.")

        for key in ("unit_price", "price_paid", "unit_price_local", "price_local"):
            data[key] = to_decimal(data.get(key), Q3)
            if data[key] is not None and data[key] < 0:
                errors.append("Cena nemůže být záporná.")
        if data["price_paid"] is None:
            errors.append("Cena je povinná.")

        data["currency_code"] = normalize_currency(data.get("currency_code"))

        for key, max_len in (("payment_method", 20), ("station_name", 100), ("station_address", 200), ("note", None)):
            value = data.get(key)
            value = value.strip() if isinstance(value, str) else value
            data[key] = value or None
            if value and max_len and len(value) > max_len:
                errors.append(f"Hodnota '{value}' je příliš dlouhá (max. {max_len} znaků).")

        data["full_tank"] = bool(data.get("full_tank"))
        data["skipped_refuel"] = bool(data.get("skipped_refuel"))

        if errors:
            raise ValidationError(" ".join(errors), errors)
        return {key: data[key] for key in FUEL_RECORD_FIELDS}

    def _check_odometer(self, vehicle_id, refuel_datetime, odometer, exclude_id=None):
        """Stav tachometru musí odpovídat chronologii tankování."""
        base = self.session.query(FuelRecord).filter(FuelRecord.vehicle_id == vehicle_id)
        if exclude_id is not None:
            base = base.filter(FuelRecord.id != exclude_id)

        previous = (base.filter(FuelRecord.refuel_datetime < refuel_datetime)
                    .order_by(FuelRecord.refuel_datetime.desc()).first())
        if previous and previous.odometer > odometer:
            raise ValidationError(
                f"Stav tachometru ({odometer} km) je nižší než u předchozího tankování "
                f"{previous.refuel_datetime:%d.%m.%Y} ({previous.odometer} km)."
            )

        following = (base.filter(FuelRecord.refuel_datetime > refuel_datetime)
                     .order_by(FuelRecord.refuel_datetime.asc()).first())
        if following and following.odometer < odometer:
            raise ValidationError(
                f"Stav tachometru ({odometer} km) je vyšší než u následujícího tankování "
                f"{following.refuel_datetime:%d.%m.%Y} ({following.odometer} km)."
            )
