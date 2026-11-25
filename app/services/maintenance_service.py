import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func

from models import (
    VehicleRental, ServiceRecord, ServiceInterval, DefaultServiceInterval, Reminder, Expense, Vehicle, VehicleNote, FuelRecord, TireSwap, TireTreadCheck,
)
from models.vehicle_note import NOTE_CATEGORIES
from models.maintenance import (
    REPEAT_OPTIONS, REPEAT_NONE, VIGNETTE_VARIANTS, join_service_types, split_service_types,
)
from services.errors import ValidationError, NotFoundError
from services.pricing import convert_price

# Upozorňovat, pokud ze servisního intervalu zbývá méně než 10 %
INTERVAL_WARNING_RATIO = 0.10

LEVEL_OK = "ok"
LEVEL_WARNING = "warning"
LEVEL_OVERDUE = "overdue"
LEVEL_UNKNOWN = "unknown"
_LEVEL_ORDER = {LEVEL_UNKNOWN: 0, LEVEL_OK: 1, LEVEL_WARNING: 2, LEVEL_OVERDUE: 3}


def add_months(d, months):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def shift_by_repeat(d, repeat):
    if repeat == "daily":
        return d + timedelta(days=1)
    if repeat == "weekly":
        return d + timedelta(weeks=1)
    if repeat == "monthly":
        return add_months(d, 1)
    if repeat == "yearly":
        return add_months(d, 12)
    return d


@dataclass
class DueStatus:
    """Stav termínu (servisního intervalu nebo upomínky)."""
    level: str = LEVEL_UNKNOWN
    due_date: date = None
    due_km: int = None
    days_left: int = None
    km_left: int = None
    last_date: date = None
    last_km: int = None
    messages: list = field(default_factory=list)
    text: str = None  # vlastní popis místo "za X dní / po termínu"

    @property
    def is_alert(self):
        return self.level in (LEVEL_WARNING, LEVEL_OVERDUE)

    @property
    def summary(self):
        if self.text:
            return self.text
        parts = []
        if self.days_left is not None:
            if self.days_left < 0:
                parts.append(f"po termínu {-self.days_left} dní")
            else:
                parts.append(f"za {self.days_left} dní")
        if self.km_left is not None:
            if self.km_left < 0:
                parts.append(f"překročeno o {-self.km_left:,} km".replace(",", " "))
            else:
                parts.append(f"za {self.km_left:,} km".replace(",", " "))
        return ", ".join(parts) if parts else "termín nelze určit"


def _worse(a, b):
    return a if _LEVEL_ORDER[a] >= _LEVEL_ORDER[b] else b


def _clean_str(value, max_len=None, label="Hodnota", required=False):
    value = value.strip() if isinstance(value, str) else value
    value = value or None
    if required and not value:
        raise ValidationError(f"{label} je povinná položka.")
    if value and max_len and len(value) > max_len:
        raise ValidationError(f"{label} může mít nejvýše {max_len} znaků.")
    return value


def _positive_int(value, label, allow_none=True):
    if value is None or value == "":
        if allow_none:
            return None
        raise ValidationError(f"{label} je povinná položka.")
    value = int(value)
    if value < 0:
        raise ValidationError(f"{label} nemůže být záporné číslo.")
    return value


def _insurance(data, price_local):
    """Pole pojistného plnění; bez zaškrtnutí se vymažou. Plnění je v Kč a nemůže převýšit cenu."""
    from services.pricing import to_decimal, Q3
    if not data.get("insurance_claim"):
        return {"insurance_claim": False, "insurer": None, "policy_number": None, "claim_number": None,
                "insurance_paid": None}
    paid = to_decimal(data.get("insurance_paid"), Q3)
    if paid is not None and paid < 0:
        raise ValidationError("Plnění pojišťovny nemůže být záporné.")
    if paid is not None and price_local is not None and paid > price_local:
        raise ValidationError("Plnění pojišťovny nemůže být vyšší než cena.")
    return {
        "insurance_claim": True,
        "insurer": _clean_str(data.get("insurer"), 100, "Pojišťovna"),
        "policy_number": _clean_str(data.get("policy_number"), 50, "Číslo pojistky"),
        "claim_number": _clean_str(data.get("claim_number"), 50, "Číslo pojistné události"),
        "insurance_paid": paid,
    }


def _ensure_vehicle(session, vehicle_id):
    if not vehicle_id or session.get(Vehicle, vehicle_id) is None:
        raise NotFoundError("Vozidlo nenalezeno.")


class _RecordServiceBase:
    model = None
    date_column = None

    def __init__(self, session):
        self.session = session

    def get(self, record_id):
        return self.session.get(self.model, record_id)

    def search(self, vehicle_ids, date_from=None, date_to=None, **filters):
        if not vehicle_ids:
            return []
        col = getattr(self.model, self.date_column)
        query = self.session.query(self.model).filter(self.model.vehicle_id.in_(vehicle_ids))
        if date_from:
            query = query.filter(col >= date_from)
        if date_to:
            query = query.filter(col <= date_to)
        for key, value in filters.items():
            if value:
                query = query.filter(getattr(self.model, key) == value)
        return query.order_by(col.desc(), self.model.id.desc()).all()

    def create(self, **data):
        record = self.model(**self._validate(data))
        self.session.add(record)
        self.session.commit()
        return record

    def update(self, record, data):
        current = {c.name: getattr(record, c.name) for c in self.model.__table__.columns if c.name != "id"}
        current.update(data)
        for key, value in self._validate(current).items():
            setattr(record, key, value)
        self.session.commit()
        return record

    def delete(self, record):
        self.session.delete(record)
        self.session.commit()

    def _validate(self, data):
        raise NotImplementedError


# ----------------------------------------------------------------------
# Servis
# ----------------------------------------------------------------------

class ServiceRecordService(_RecordServiceBase):
    model = ServiceRecord
    date_column = "service_date"

    def _validate(self, data, manual_rate=None):
        _ensure_vehicle(self.session, data.get("vehicle_id"))
        if not data.get("service_date"):
            raise ValidationError("Datum servisu je povinné.")
        date_to = data.get("date_to") or None
        service_time, time_to = data.get("service_time") or None, data.get("time_to") or None
        if date_to and date_to < data["service_date"]:
            raise ValidationError("Vyzvednutí ze servisu nemůže být před předáním.")
        if time_to and not date_to:
            raise ValidationError("K času vyzvednutí vyplňte i datum vyzvednutí.")
        if date_to == data["service_date"] and service_time and time_to and time_to < service_time:
            raise ValidationError("Čas vyzvednutí nemůže být před časem předání.")
        km_from = _positive_int(data.get("odometer"), "Stav tachometru")
        km_to = _positive_int(data.get("odometer_to"), "Km při vyzvednutí")
        if km_from is not None and km_to is not None and km_to < km_from:
            raise ValidationError("Km při vyzvednutí nemohou být menší než při předání.")
        manual_rate = data.pop("manual_rate", None)
        currency, price_paid, price_local = convert_price(
            data.get("price_paid"), data.get("currency_code"), data["service_date"], manual_rate)
        return {
            "vehicle_id": data["vehicle_id"],
            "service_date": data["service_date"],
            "service_time": service_time,
            "odometer": km_from,
            "date_to": date_to,
            "time_to": time_to,
            "odometer_to": km_to,
            "in_progress": bool(data.get("in_progress")) and not date_to,  # vyzvednutím servis končí
            "service_type": _clean_str(join_service_types([data.get("service_type") or ""]), 255,
                                       "Typ servisu", required=True),
            "place": _clean_str(data.get("place"), 100, "Místo"),
            "price_paid": price_paid,
            "currency_code": currency,
            "price_local": price_local,
            "note": _clean_str(data.get("note")),
            **_insurance(data, price_local),
        }

    def search(self, vehicle_ids, date_from=None, date_to=None, service_type=None, **filters):
        """Filtr podle typu najde i servisy, kde byl typ jednou z více položek."""
        records = super().search(vehicle_ids, date_from, date_to, **filters)
        if service_type:
            wanted = service_type.strip().lower()
            records = [r for r in records if wanted in (t.lower() for t in r.types)]
        return records

    def get_service_types(self, vehicle_ids):
        """Všechny použité položky servisu (i z vícepoložkových záznamů)."""
        if not vehicle_ids:
            return []
        rows = (self.session.query(ServiceRecord.service_type)
                .filter(ServiceRecord.vehicle_id.in_(vehicle_ids)).distinct().all())
        types = {}
        for (value,) in rows:
            for t in split_service_types(value):
                types.setdefault(t.lower(), t)
        return sorted(types.values(), key=str.lower)

    def get_last_service(self, vehicle_id, service_type):
        """Poslední servis, který obsahoval danou položku (sám nebo spolu s dalšími)."""
        wanted = service_type.strip().lower()
        pattern = f"%{wanted}%"
        candidates = (self.session.query(ServiceRecord)
                      .filter(ServiceRecord.vehicle_id == vehicle_id,
                              func.lower(ServiceRecord.service_type).like(pattern))
                      .order_by(ServiceRecord.service_date.desc(), ServiceRecord.id.desc()))
        return next((r for r in candidates if wanted in (t.lower() for t in r.types)), None)


# ----------------------------------------------------------------------
# Výdaje
# ----------------------------------------------------------------------

def vignette_valid_until(valid_from, variant):
    """Poslední den platnosti dálniční známky (platí včetně prvního dne)."""
    if variant not in VIGNETTE_VARIANTS:
        raise ValidationError("Neplatný typ dálniční známky.")
    until = valid_from + timedelta(days=VIGNETTE_VARIANTS[variant][1] - 1)
    if variant == "year" and _includes_leap_day(valid_from, until):
        until += timedelta(days=1)  # roční známka platí 366 dní, pokud období zahrnuje 29. únor
    return until


def _includes_leap_day(start, end):
    return any(calendar.isleap(year) and start <= date(year, 2, 29) <= end
               for year in range(start.year, end.year + 1))


# Upozornit na konec platnosti tolik dní předem (krátké známky dřív nedává smysl)
def _notify_days_for(valid_from, valid_until):
    if valid_from is None:
        return 14
    length = (valid_until - valid_from).days + 1
    return 14 if length > 60 else (3 if length > 7 else 0)


class ExpenseService(_RecordServiceBase):
    """
    Výdaje. U výdaje s platností (dálniční známka, pojištění…) lze nechat vytvořit upomínku
    konce platnosti; při zápisu nové známky / pojistky se upomínka té předchozí uzavře.
    """
    model = Expense
    date_column = "expense_date"

    def create(self, **data):
        remind = bool(data.pop("remind", False))
        record = super().create(**data)
        self._sync_reminder(record, remind)
        return record

    def update(self, record, data):
        data = dict(data)
        remind = bool(data.pop("remind", False))
        record = super().update(record, data)
        self._sync_reminder(record, remind)
        return record

    def delete(self, record):
        reminder = record.reminder
        if reminder is not None and not reminder.is_done:
            self.session.delete(reminder)
        super().delete(record)

    def _sync_reminder(self, record, remind):
        reminder = record.reminder
        if remind and record.valid_until:
            title = f"{record.category} – konec platnosti"[:100]
            if reminder is None:
                reminder = Reminder(vehicle_id=record.vehicle_id, repeat=REPEAT_NONE, notify_km_before=0)
                self.session.add(reminder)
                record.reminder = reminder
            reminder.vehicle_id = record.vehicle_id
            reminder.title = title
            reminder.due_date = record.valid_until
            reminder.due_odometer = None
            reminder.notify_days_before = _notify_days_for(record.valid_from, record.valid_until)
            reminder.note = f"Vytvořeno automaticky z výdaje ze dne {record.expense_date.strftime('%d.%m.%Y')}."
            reminder.is_done = False
            self._close_previous(record)
        elif reminder is not None:
            record.reminder = None
            if not reminder.is_done:
                self.session.delete(reminder)
        self.session.commit()

    def _close_previous(self, record):
        """Obnovení (nová známka/pojistka) - upomínky dřívějších výdajů stejné kategorie jsou vyřízené."""
        previous = (self.session.query(Expense)
                    .filter(Expense.vehicle_id == record.vehicle_id, Expense.category == record.category,
                            Expense.id != record.id, Expense.reminder_id.isnot(None),
                            Expense.valid_until <= record.valid_until)
                    .all())
        for expense in previous:
            if expense.reminder is not None:
                expense.reminder.is_done = True

    def current_validities(self, vehicle_id, today=None):
        """Nejnovější platnost pro každou kategorii: [(kategorie, výdaj, dní do konce, začátek obnovy)]."""
        today = today or date.today()
        latest = {}
        for e in (self.session.query(Expense)
                  .filter(Expense.vehicle_id == vehicle_id, Expense.valid_until.isnot(None))
                  .order_by(Expense.valid_until)):
            latest[e.category] = e
        return [(cat, e, (e.valid_until - today).days, max(today, e.valid_until + timedelta(days=1)))
                for cat, e in sorted(latest.items())]

    def _validate(self, data):
        _ensure_vehicle(self.session, data.get("vehicle_id"))
        if not data.get("expense_date"):
            raise ValidationError("Datum výdaje je povinné.")
        if data.get("price_paid") in (None, ""):
            raise ValidationError("Částka je povinná.")
        manual_rate = data.pop("manual_rate", None)
        variant = data.pop("vignette_variant", None)
        valid_from = data.get("valid_from") or None
        valid_until = data.get("valid_until") or None
        if variant:
            valid_from = valid_from or data["expense_date"]
            valid_until = vignette_valid_until(valid_from, variant)
        if valid_from and valid_until and valid_until < valid_from:
            raise ValidationError("Konec platnosti nemůže být před jejím začátkem.")
        if not valid_until:
            valid_from = None  # bez konce platnosti nemá začátek význam
        currency, price_paid, price_local = convert_price(
            data.get("price_paid"), data.get("currency_code"), data["expense_date"], manual_rate)
        return {
            "valid_from": valid_from,
            "valid_until": valid_until,
            "vehicle_id": data["vehicle_id"],
            "expense_date": data["expense_date"],
            "category": _clean_str(data.get("category"), 30, "Kategorie", required=True),
            "description": _clean_str(data.get("description"), 200, "Popis"),
            "odometer": _positive_int(data.get("odometer"), "Stav tachometru"),
            "price_paid": price_paid,
            "currency_code": currency,
            "price_local": price_local,
            "note": _clean_str(data.get("note")),
            **_insurance(data, price_local),
        }


# ----------------------------------------------------------------------
# Půjčení vozidla
# ----------------------------------------------------------------------

class RentalService(_RecordServiceBase):
    """Jednotlivá půjčení půjčeného vozidla (půjčovna / od koho, období, km, půjčovné)."""
    model = VehicleRental
    date_column = "date_from"

    def _validate(self, data):
        _ensure_vehicle(self.session, data.get("vehicle_id"))
        if not self.session.get(Vehicle, data["vehicle_id"]).is_rental:
            raise ValidationError("Vozidlo není označené jako půjčené.")
        if not data.get("date_from"):
            raise ValidationError("Datum půjčení je povinné.")
        date_to = data.get("date_to") or None
        if date_to and date_to < data["date_from"]:
            raise ValidationError("Konec půjčení nemůže být před jeho začátkem.")
        time_from, time_to = data.get("time_from") or None, data.get("time_to") or None
        if time_to and not date_to:
            raise ValidationError("K času vrácení vyplňte i datum vrácení.")
        if date_to == data["date_from"] and time_from and time_to and time_to < time_from:
            raise ValidationError("Čas vrácení nemůže být před časem půjčení.")
        km_from = _positive_int(data.get("odometer_from"), "Kilometry při půjčení")
        km_to = _positive_int(data.get("odometer_to"), "Kilometry při vrácení")
        if km_from is not None and km_to is not None and km_to < km_from:
            raise ValidationError("Kilometry při vrácení nemohou být menší než při půjčení.")
        manual_rate = data.get("manual_rate")
        currency, price_paid, price_local = convert_price(
            data.get("price_paid"), data.get("currency_code"), data["date_from"], manual_rate)
        return {
            "vehicle_id": data["vehicle_id"],
            "provider": _clean_str(data.get("provider"), 100, "Půjčovna / od koho"),  # jen starší záznamy
            "date_from": data["date_from"],
            "time_from": time_from,
            "date_to": date_to,
            "time_to": time_to,
            "odometer_from": km_from,
            "odometer_to": km_to,
            "price_paid": price_paid,
            "currency_code": currency,
            "price_local": price_local,
            "note": _clean_str(data.get("note")),
        }


# ----------------------------------------------------------------------
# Pravidelný servis
# ----------------------------------------------------------------------

@dataclass
class EffectiveInterval:
    """Univerzální interval použitý u konkrétního vozidla (vozidlo ho nemá nastavené samo)."""
    vehicle: object
    default: DefaultServiceInterval
    is_default: bool = True
    is_active: bool = True
    id: int = None
    start_date: date = None
    start_odometer: int = None
    note: str = None

    @property
    def vehicle_id(self):
        return self.vehicle.id

    @property
    def service_type(self):
        return self.default.service_type

    @property
    def interval_months(self):
        return self.default.interval_months

    @property
    def interval_km(self):
        return self.default.interval_km


class DefaultIntervalService:
    """Univerzální servisní intervaly uživatele (vlastníka vozidel)."""

    def __init__(self, session):
        self.session = session

    def list_for_user(self, user_id):
        return (self.session.query(DefaultServiceInterval)
                .filter(DefaultServiceInterval.user_id == user_id)
                .order_by(DefaultServiceInterval.service_type).all())

    def get(self, interval_id, user_id):
        interval = self.session.get(DefaultServiceInterval, interval_id)
        if interval is None or interval.user_id != user_id:
            raise NotFoundError("Interval nenalezen.")
        return interval

    def _validate(self, user_id, data, exclude_id=None):
        service_type = _clean_str(data.get("service_type"), 50, "Typ servisu", required=True)
        months = _positive_int(data.get("interval_months"), "Časový interval")
        km = _positive_int(data.get("interval_km"), "Kilometrový interval")
        if not months and not km:
            raise ValidationError("Zadejte časový nebo kilometrový interval (nebo oba).")
        kind = data.get("vehicle_kind") or None
        if kind not in (None, "car", "moto"):
            raise ValidationError("Neplatný druh vozidla.")
        for other in self.list_for_user(user_id):
            overlap = kind is None or other.vehicle_kind is None or other.vehicle_kind == kind
            if other.id != exclude_id and overlap and other.service_type.lower() == service_type.lower():
                raise ValidationError(f"Interval „{service_type}“ už máte nastavený.")
        return {"service_type": service_type, "interval_months": months or None, "interval_km": km or None,
                "vehicle_kind": kind}

    def create(self, user_id, data):
        interval = DefaultServiceInterval(user_id=user_id, **self._validate(user_id, data))
        self.session.add(interval)
        self.session.commit()
        return interval

    def update(self, interval, data):
        for key, value in self._validate(interval.user_id, data, interval.id).items():
            setattr(interval, key, value)
        self.session.commit()
        return interval

    def delete(self, interval):
        self.session.delete(interval)
        self.session.commit()

    def add_suggested(self, user_id):
        from models.maintenance import SUGGESTED_INTERVALS
        existing = {i.service_type.lower() for i in self.list_for_user(user_id)}
        for service_type, kind, months, km in SUGGESTED_INTERVALS:
            if service_type.lower() not in existing:
                self.session.add(DefaultServiceInterval(user_id=user_id, service_type=service_type,
                                                        vehicle_kind=kind, interval_months=months,
                                                        interval_km=km))
        self.session.commit()


class ServiceIntervalService(_RecordServiceBase):
    model = ServiceInterval
    date_column = "id"

    def list_for_vehicles(self, vehicle_ids, only_active=True):
        if not vehicle_ids:
            return []
        query = self.session.query(ServiceInterval).filter(ServiceInterval.vehicle_id.in_(vehicle_ids))
        if only_active:
            query = query.filter(ServiceInterval.is_active.is_(True))
        return query.order_by(ServiceInterval.vehicle_id, ServiceInterval.service_type).all()

    def effective_for_vehicles(self, vehicles, only_active=True):
        """Intervaly vozidel včetně univerzálních intervalů vlastníka.

        Interval nastavený u vozidla má přednost před univerzálním se stejným typem servisu
        (i vypnutý - tím jde univerzální interval u vozidla vypnout).
        """
        vehicles = list(vehicles)
        own = self.list_for_vehicles([v.id for v in vehicles], only_active=False)
        owner_ids = {v.owner_id for v in vehicles if v.owner_id}
        defaults = []
        if owner_ids:
            defaults = (self.session.query(DefaultServiceInterval)
                        .filter(DefaultServiceInterval.user_id.in_(owner_ids))
                        .order_by(DefaultServiceInterval.service_type).all())
        result = []
        for vehicle in vehicles:
            mine = [i for i in own if i.vehicle_id == vehicle.id]
            taken = {i.service_type.lower() for i in mine}
            items = [i for i in mine if i.is_active or not only_active]
            for d in defaults:
                if d.user_id == vehicle.owner_id and d.applies_to(vehicle) and d.service_type.lower() not in taken:
                    taken.add(d.service_type.lower())
                    items.append(EffectiveInterval(vehicle, d))
            result.extend(sorted(items, key=lambda i: i.service_type.lower()))
        return result

    def _validate(self, data):
        _ensure_vehicle(self.session, data.get("vehicle_id"))
        months = _positive_int(data.get("interval_months"), "Časový interval")
        km = _positive_int(data.get("interval_km"), "Kilometrový interval")
        if not months and not km:
            raise ValidationError("Zadejte časový nebo kilometrový interval (nebo oba).")
        return {
            "vehicle_id": data["vehicle_id"],
            "service_type": _clean_str(data.get("service_type"), 50, "Typ servisu", required=True),
            "interval_months": months or None,
            "interval_km": km or None,
            "start_date": data.get("start_date") or None,
            "start_odometer": _positive_int(data.get("start_odometer"), "Výchozí stav tachometru"),
            "note": _clean_str(data.get("note")),
            "is_active": True if data.get("is_active") is None else bool(data.get("is_active")),
        }

    def get_status(self, interval, current_odometer, today=None):
        today = today or date.today()
        last = ServiceRecordService(self.session).get_last_service(interval.vehicle_id, interval.service_type)
        status = DueStatus()
        status.last_date = last.service_date if last else interval.start_date
        status.last_km = last.odometer if last and last.odometer is not None else interval.start_odometer

        level = LEVEL_UNKNOWN
        if interval.interval_months and status.last_date:
            status.due_date = add_months(status.last_date, interval.interval_months)
            status.days_left = (status.due_date - today).days
            total_days = (status.due_date - status.last_date).days or 1
            if status.days_left < 0:
                level = _worse(level, LEVEL_OVERDUE)
            elif status.days_left < total_days * INTERVAL_WARNING_RATIO:
                level = _worse(level, LEVEL_WARNING)
            else:
                level = _worse(level, LEVEL_OK)

        if interval.interval_km and status.last_km is not None:
            status.due_km = status.last_km + interval.interval_km
            if current_odometer is not None:
                status.km_left = status.due_km - current_odometer
                if status.km_left < 0:
                    level = _worse(level, LEVEL_OVERDUE)
                elif status.km_left < interval.interval_km * INTERVAL_WARNING_RATIO:
                    level = _worse(level, LEVEL_WARNING)
                else:
                    level = _worse(level, LEVEL_OK)

        status.level = level
        return status


# ----------------------------------------------------------------------
# Upomínky
# ----------------------------------------------------------------------

class ReminderService(_RecordServiceBase):
    model = Reminder
    date_column = "due_date"

    def list_for_vehicles(self, vehicle_ids, include_done=False):
        if not vehicle_ids:
            return []
        query = self.session.query(Reminder).filter(Reminder.vehicle_id.in_(vehicle_ids))
        if not include_done:
            query = query.filter(Reminder.is_done.is_(False))
        return query.order_by(Reminder.is_done, Reminder.due_date.is_(None), Reminder.due_date,
                              Reminder.id).all()

    def _validate(self, data):
        _ensure_vehicle(self.session, data.get("vehicle_id"))
        repeat = data.get("repeat") or REPEAT_NONE
        if repeat not in REPEAT_OPTIONS:
            raise ValidationError("Neplatné opakování.")
        due_date = data.get("due_date") or None
        due_odometer = _positive_int(data.get("due_odometer"), "Stav tachometru")
        repeat_km = _positive_int(data.get("repeat_km"), "Opakování po km")
        if not due_date and due_odometer is None:
            raise ValidationError("Zadejte datum nebo stav tachometru (nebo obojí).")
        if repeat != REPEAT_NONE and not due_date:
            raise ValidationError("Opakování podle data vyžaduje zadané datum.")
        if repeat_km and due_odometer is None:
            raise ValidationError("Opakování po km vyžaduje zadaný stav tachometru.")
        notify_days = _positive_int(data.get("notify_days_before"), "Upozornit dní předem")
        notify_km = _positive_int(data.get("notify_km_before"), "Upozornit km předem")
        return {
            "vehicle_id": data["vehicle_id"],
            "title": _clean_str(data.get("title"), 100, "Název", required=True),
            "note": _clean_str(data.get("note")),
            "due_date": due_date,
            "due_odometer": due_odometer,
            "repeat": repeat,
            "repeat_km": repeat_km or None,
            "notify_days_before": 14 if notify_days is None else notify_days,
            "notify_km_before": 500 if notify_km is None else notify_km,
            "is_done": bool(data.get("is_done")),
        }

    def get_status(self, reminder, current_odometer, today=None):
        today = today or date.today()
        status = DueStatus(due_date=reminder.due_date, due_km=reminder.due_odometer)
        if reminder.is_done:
            status.level = LEVEL_OK
            return status

        level = LEVEL_UNKNOWN
        if reminder.due_date:
            status.days_left = (reminder.due_date - today).days
            if status.days_left < 0:
                level = _worse(level, LEVEL_OVERDUE)
            elif status.days_left <= reminder.notify_days_before:
                level = _worse(level, LEVEL_WARNING)
            else:
                level = _worse(level, LEVEL_OK)
        if reminder.due_odometer is not None and current_odometer is not None:
            status.km_left = reminder.due_odometer - current_odometer
            if status.km_left < 0:
                level = _worse(level, LEVEL_OVERDUE)
            elif status.km_left <= reminder.notify_km_before:
                level = _worse(level, LEVEL_WARNING)
            else:
                level = _worse(level, LEVEL_OK)
        status.level = level
        return status

    def complete(self, reminder, current_odometer=None, today=None):
        """Označí upomínku jako vyřízenou; opakovanou posune na další termín."""
        today = today or date.today()
        if reminder.repeat == REPEAT_NONE and not reminder.repeat_km:
            reminder.is_done = True
        else:
            if reminder.repeat != REPEAT_NONE and reminder.due_date:
                next_date = shift_by_repeat(reminder.due_date, reminder.repeat)
                # Pokud byla upomínka dlouho po termínu, posuneme ji až za dnešek
                while next_date <= today:
                    next_date = shift_by_repeat(next_date, reminder.repeat)
                reminder.due_date = next_date
            if reminder.repeat_km and reminder.due_odometer is not None:
                next_km = reminder.due_odometer + reminder.repeat_km
                while current_odometer is not None and next_km <= current_odometer:
                    next_km += reminder.repeat_km
                reminder.due_odometer = next_km
        self.session.commit()
        return reminder

    def reopen(self, reminder):
        reminder.is_done = False
        self.session.commit()
        return reminder


# ----------------------------------------------------------------------
# Přehled upozornění
# ----------------------------------------------------------------------

@dataclass
class Alert:
    vehicle: object
    kind: str           # "interval" | "reminder" | "tires"
    title: str
    status: DueStatus
    item: object


def collect_alerts(session, vehicles, only_alerts=True, today=None):
    """Upozornění (servisní intervaly + upomínky) pro dané vozidla, seřazená podle naléhavosti."""
    from services.vehicle_service import VehicleService

    vehicle_service = VehicleService(session)
    interval_service = ServiceIntervalService(session)
    reminder_service = ReminderService(session)
    vehicles_by_id = {v.id: v for v in vehicles}
    ids = list(vehicles_by_id)
    odometers = {vid: vehicle_service.get_current_odometer(vid) for vid in ids}

    alerts = []
    for interval in interval_service.effective_for_vehicles(vehicles):
        status = interval_service.get_status(interval, odometers[interval.vehicle_id], today)
        if status.is_alert or not only_alerts:
            alerts.append(Alert(vehicles_by_id[interval.vehicle_id], "interval",
                                interval.service_type, status, interval))
    for reminder in reminder_service.list_for_vehicles(ids):
        status = reminder_service.get_status(reminder, odometers[reminder.vehicle_id], today)
        if status.is_alert or not only_alerts:
            alerts.append(Alert(vehicles_by_id[reminder.vehicle_id], "reminder",
                                reminder.title, status, reminder))
    from services.tire_service import tire_alerts  # tire_service importuje tento modul
    for vehicle, tire_set, status in tire_alerts(session, list(vehicles_by_id.values()), today):
        alerts.append(Alert(vehicle, "tires", "Zimní pneumatiky", status, tire_set))

    def sort_key(alert):
        s = alert.status
        return (-_LEVEL_ORDER[s.level],
                s.days_left if s.days_left is not None else 10 ** 6,
                s.km_left if s.km_left is not None else 10 ** 9)

    return sorted(alerts, key=sort_key)


# ----------------------------------------------------------------------
# Poznámky k vozidlu
# ----------------------------------------------------------------------

def check_odometer_order(session, vehicle_id, when, odometer, has_time=True, exclude=(None, None)):
    """Stav tachometru musí odpovídat ostatním záznamům vozidla v čase (poznámky, přezutí).

    Stejný stav v různé dny je v pořádku (motorka přes zimu v garáži). Záznamy jen s datem
    (servis, výdaje, přezutí) se se záznamem ze stejného dne neporovnávají.
    exclude = ("note" | "tire_swap" | "tread_check", id) - upravovaný záznam se neporovnává sám se sebou.
    """
    kind, exclude_id = exclude
    readings = []  # (čas, km, popis, má čas)
    for at, km in (session.query(FuelRecord.refuel_datetime, FuelRecord.odometer)
                   .filter(FuelRecord.vehicle_id == vehicle_id)):
        readings.append((at, km, "tankování", True))
    for at, km, rid in (session.query(VehicleNote.note_datetime, VehicleNote.odometer, VehicleNote.id)
                        .filter(VehicleNote.vehicle_id == vehicle_id, VehicleNote.odometer.isnot(None))):
        if not (kind == "note" and rid == exclude_id):
            readings.append((at, km, "poznámky", True))
    for d, km, rid in (session.query(TireSwap.swap_date, TireSwap.odometer, TireSwap.id)
                       .filter(TireSwap.vehicle_id == vehicle_id)):
        if not (kind == "tire_swap" and rid == exclude_id):
            readings.append((datetime.combine(d, datetime.min.time()), km, "přezutí", False))
    for d, km, rid in (session.query(TireTreadCheck.check_date, TireTreadCheck.odometer, TireTreadCheck.id)
                       .filter(TireTreadCheck.vehicle_id == vehicle_id)):
        if not (kind == "tread_check" and rid == exclude_id):
            readings.append((datetime.combine(d, datetime.min.time()), km, "kontroly dezénu", False))
    for model, column, label in ((ServiceRecord, ServiceRecord.service_date, "servisu"),
                                 (Expense, Expense.expense_date, "výdaje")):
        for d, km in (session.query(column, model.odometer)
                      .filter(model.vehicle_id == vehicle_id, model.odometer.isnot(None))):
            readings.append((datetime.combine(d, datetime.min.time()), km, label, False))

    for at, km, label, reading_has_time in readings:
        if has_time and reading_has_time:
            before, after = at < when, at > when
        else:
            before, after = at.date() < when.date(), at.date() > when.date()
        if before and km > odometer:
            raise ValidationError(f"Stav tachometru ({odometer} km) je nižší než u {label} "
                                  f"{at:%d.%m.%Y} ({km} km).")
        if after and km < odometer:
            raise ValidationError(f"Stav tachometru ({odometer} km) je vyšší než u {label} "
                                  f"{at:%d.%m.%Y} ({km} km).")


class VehicleNoteService(_RecordServiceBase):
    model = VehicleNote
    date_column = "note_datetime"

    def _validate(self, data):
        _ensure_vehicle(self.session, data.get("vehicle_id"))
        if not data.get("note_datetime"):
            raise ValidationError("Datum a čas poznámky jsou povinné.")
        category = _clean_str(data.get("category"), 40, "Typ")
        text = _clean_str(data.get("text"), 5000, "Poznámka")
        if not category and not text:
            raise ValidationError("Vyplňte typ nebo text poznámky.")
        odometer = _positive_int(data.get("odometer"), "Stav tachometru")
        if odometer is not None:
            self._check_odometer(data["vehicle_id"], data["note_datetime"], odometer, data.get("id"))
        return {
            "vehicle_id": data["vehicle_id"],
            "note_datetime": data["note_datetime"],
            "odometer": odometer,
            "category": category,
            "text": text,
            "created_by_id": data.get("created_by_id"),
        }

    def update(self, record, data):
        # id, aby se poznámka při kontrole tachometru neporovnávala sama se sebou
        return super().update(record, {**data, "id": record.id})

    def _check_odometer(self, vehicle_id, when, odometer, exclude_id=None):
        check_odometer_order(self.session, vehicle_id, when, odometer, exclude=("note", exclude_id))

    def get_categories(self, vehicle_ids):
        """Návrhy typu: výchozí + dříve použité."""
        used = []
        if vehicle_ids:
            used = [r[0] for r in self.session.query(VehicleNote.category)
                    .filter(VehicleNote.vehicle_id.in_(vehicle_ids), VehicleNote.category.isnot(None)).distinct()]
        seen, result = set(), []
        for name in NOTE_CATEGORIES + sorted(used):
            if name.lower() not in seen:
                seen.add(name.lower())
                result.append(name)
        return result
