"""Servis, pravidelný servis, upomínky a výdaje."""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from models.maintenance import (
    SERVICE_TYPES, EXPENSE_CATEGORIES, join_service_types, split_service_types, REPEAT_OPTIONS, VALIDITY_CATEGORIES, VIGNETTE_CATEGORY, VIGNETTE_VARIANTS,
)
from models.vehicle import ROLE_EDITOR
from services.maintenance_service import (
    RentalService, DefaultIntervalService, ServiceRecordService, ServiceIntervalService, ReminderService, ExpenseService, VehicleNoteService,
    collect_alerts,
)
from services.vehicle_service import VehicleService
from web.common import (
    visible_vehicles, check_record_access, default_filter_period, csv_response, decimal_csv,
)
from web.crud import CrudConfig, register_crud
from web.deps import get_db, get_current_user, flash, render
from services.errors import ValidationError
from web.forms import FormReader, iso, parse_filter_date, parse_filter_int, rate_from_record

router = APIRouter()


def _list_filters(request, db, user):
    q = request.query_params
    vehicles = visible_vehicles(db, user)
    vehicle_id = parse_filter_int(q.get("vehicle_id"))
    ids = [v.id for v in vehicles if vehicle_id in (None, v.id)]
    if q.get("all"):
        date_from = date_to = None
    else:
        date_from, date_to = default_filter_period(parse_filter_date(q.get("date_from")),
                                                   parse_filter_date(q.get("date_to")))
    filters = {"vehicle_id": vehicle_id, "date_from": iso(date_from), "date_to": iso(date_to),
               "all": q.get("all", ""), "category": q.get("category", ""), "service_type": q.get("service_type", "")}
    return vehicles, ids, date_from, date_to, filters


def _check_not_future(d, label):
    from services.errors import ValidationError
    if d and d > date.today():
        raise ValidationError(f"{label} nemůže být v budoucnosti.")


# ======================================================================
# Servis
# ======================================================================

TYPE_PREFIX = "st:"  # zaškrtávací pole položek servisu: name="st:Výměna oleje"


def _read_service(form):
    checked = [key[len(TYPE_PREFIX):] for key in form.raw if key.startswith(TYPE_PREFIX) and form.raw[key]]
    # starší tvar formuláře (jedno textové pole) i vlastní položky v poli "Jiné"
    service_type = join_service_types(checked + [form.raw.get("service_type_other") or "",
                                                 form.raw.get("service_type") or ""])
    if not service_type:
        form.errors.append("Typ servisu: zaškrtněte alespoň jednu položku nebo vyplňte jinou.")
    elif len(service_type) > 255:
        form.errors.append("Typ servisu: nejvýše 255 znaků.")
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "service_date": form.date("service_date", "Datum", required=True),
        "odometer": form.int("odometer", "Stav tachometru", min_value=0),
        "service_type": service_type,
        "place": form.str("place", "Místo", max_len=100),
        "price_paid": form.decimal("price_paid", "Cena", min_value=0),
        "currency_code": form.str("currency_code", "Měna") or "CZK",
        "manual_rate": form.decimal("manual_rate", "Kurz", positive=True),
        "note": form.str("note", "Poznámka"),
        "insurance_claim": form.bool("insurance_claim"),
        "insurer": form.str("insurer", "Pojišťovna", max_len=100),
        "policy_number": form.str("policy_number", "Číslo pojistky", max_len=50),
        "claim_number": form.str("claim_number", "Číslo pojistné události", max_len=50),
        "insurance_paid": form.decimal("insurance_paid", "Uhradila pojišťovna", min_value=0),
    }
    form.check()
    _check_not_future(data["service_date"], "Datum servisu")
    return data


def _insurance_values(r):
    return {"insurance_claim": "on" if r.insurance_claim else "", "insurer": r.insurer or "",
            "policy_number": r.policy_number or "", "claim_number": r.claim_number or "",
            "insurance_paid": iso(r.insurance_paid)}


def _service_values(r):
    values = {
        "vehicle_id": str(r.vehicle_id), "service_date": iso(r.service_date), "odometer": iso(r.odometer),
        "place": r.place or "", "price_paid": iso(r.price_paid),
        "currency_code": r.currency_code, "manual_rate": rate_from_record(r), "note": r.note or "",
        **_insurance_values(r),
    }
    for t in split_service_types(r.service_type):
        values[TYPE_PREFIX + t] = "on"
    return values


def _service_context(db, user):
    """Nabídka položek: výchozí seznam + vlastní položky z dřívějších servisů."""
    known = {t.lower() for t in SERVICE_TYPES}
    used = ServiceRecordService(db).get_service_types(VehicleService(db).get_accessible_ids(user))
    return {"service_types": SERVICE_TYPES + [t for t in used if t.lower() not in known],
            "type_prefix": TYPE_PREFIX}


register_crud(router, CrudConfig(
    prefix="/services",
    service_cls=ServiceRecordService,
    template="maintenance/service_form.html",
    read_form=_read_service,
    to_values=_service_values,
    default_values=lambda vid: {"service_date": date.today().isoformat(), "currency_code": "CZK"},
    extra_context=_service_context,
    messages={"created": "Servis byl uložen.", "deleted": "Servisní záznam byl smazán."},
))


@router.get("/services")
async def list_services(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    vehicles, ids, date_from, date_to, filters = _list_filters(request, db, user)
    records = ServiceRecordService(db).search(ids, date_from, date_to, service_type=filters["service_type"])

    # Přehled pravidelných servisů všech vybraných vozidel
    vehicle_service = VehicleService(db)
    interval_service = ServiceIntervalService(db)
    odometers = {vid: vehicle_service.get_current_odometer(vid) for vid in ids}
    selected = [v for v in vehicles if v.id in ids and v.in_use]
    intervals = [(i, interval_service.get_status(i, odometers[i.vehicle_id]))
                 for i in interval_service.effective_for_vehicles(selected, only_active=False)]

    return render(request, "maintenance/service_list.html", vehicles=vehicles, records=records,
                  intervals=intervals, filters=filters,
                  total=sum((r.own_cost or 0 for r in records), 0),
                  service_types=ServiceRecordService(db).get_service_types(ids),
                  editable_ids=set(vehicle_service.get_accessible_ids(user, ROLE_EDITOR)))


@router.get("/services/export.csv")
async def export_services(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    _, ids, date_from, date_to, filters = _list_filters(request, db, user)
    records = ServiceRecordService(db).search(ids, date_from, date_to, service_type=filters["service_type"])
    rows = [(r.vehicle.display_name, r.service_date, r.odometer, r.service_type, r.place,
             decimal_csv(r.price_paid), r.currency_code, decimal_csv(r.price_local),
             decimal_csv(r.insurance_paid), r.insurer, r.note) for r in records]
    return csv_response("servis.csv", ["Vozidlo", "Datum", "Tachometr", "Typ", "Místo", "Cena", "Měna",
                                       "Cena CZK", "Uhradila pojišťovna", "Pojišťovna", "Poznámka"], rows)


# ======================================================================
# Pravidelný servis (intervaly)
# ======================================================================

def _read_interval(form):
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "service_type": form.str("service_type", "Typ servisu", required=True, max_len=50),
        "interval_months": form.int("interval_months", "Interval (měsíce)", min_value=1, max_value=240),
        "interval_km": form.int("interval_km", "Interval (km)", min_value=1),
        "start_date": form.date("start_date", "Výchozí datum"),
        "start_odometer": form.int("start_odometer", "Výchozí tachometr", min_value=0),
        "note": form.str("note", "Poznámka"),
        "is_active": form.bool("is_active"),
    }
    form.check()
    return data


def _interval_values(i):
    return {
        "vehicle_id": str(i.vehicle_id), "service_type": i.service_type,
        "interval_months": iso(i.interval_months), "interval_km": iso(i.interval_km),
        "start_date": iso(i.start_date), "start_odometer": iso(i.start_odometer),
        "note": i.note or "", "is_active": "on" if i.is_active else "",
    }


register_crud(router, CrudConfig(
    prefix="/intervals",
    service_cls=ServiceIntervalService,
    template="maintenance/interval_form.html",
    read_form=_read_interval,
    to_values=_interval_values,
    default_values=lambda vid: {"is_active": "on", "start_date": date.today().isoformat()},
    extra_context=lambda db, user: {"service_types": SERVICE_TYPES},
    prefill_params=("service_type", "interval_months", "interval_km"),
    messages={"created": "Pravidelný servis byl nastaven.", "deleted": "Pravidelný servis byl odstraněn."},
))


# ----------------------------------------------------------------------
# Půjčení vozidla (u vozidla označeného jako půjčené, opakovaně)
# ----------------------------------------------------------------------

def _read_rental(form):
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "date_from": form.date("date_from", "Půjčeno od", required=True),
        "time_from": form.time("time_from", "Čas půjčení"),
        "date_to": form.date("date_to", "Půjčeno do"),
        "time_to": form.time("time_to", "Čas vrácení"),
        "odometer_from": form.int("odometer_from", "Km při půjčení", min_value=0),
        "odometer_to": form.int("odometer_to", "Km při vrácení", min_value=0),
        "price_paid": form.decimal("price_paid", "Půjčovné", min_value=0),
        "currency_code": form.str("currency_code", "Měna") or "CZK",
        "manual_rate": form.decimal("manual_rate", "Kurz", positive=True),
        "note": form.str("note", "Poznámka"),
    }
    form.check()
    return data


def _rental_values(r):
    return {
        "vehicle_id": str(r.vehicle_id), "date_from": iso(r.date_from),
        "time_from": r.time_from.strftime("%H:%M") if r.time_from else "",
        "date_to": iso(r.date_to), "time_to": r.time_to.strftime("%H:%M") if r.time_to else "",
        "odometer_from": iso(r.odometer_from), "odometer_to": iso(r.odometer_to),
        "price_paid": iso(r.price_paid), "currency_code": r.currency_code, "manual_rate": rate_from_record(r),
        "note": r.note or "",
    }


def _rental_context(db, user):
    from web.common import editable_vehicles
    vehicles = editable_vehicles(db, user)
    return {"vehicles": [v for v in vehicles if v.is_rental]}


register_crud(router, CrudConfig(
    prefix="/rentals",
    service_cls=RentalService,
    template="maintenance/rental_form.html",
    read_form=_read_rental,
    to_values=_rental_values,
    default_values=lambda vid: {"date_from": date.today().isoformat(), "currency_code": "CZK"},
    extra_context=_rental_context,
    messages={"created": "Půjčení bylo uloženo.", "deleted": "Půjčení bylo smazáno."},
))


# ----------------------------------------------------------------------
# Univerzální intervaly (platí pro všechna vozidla uživatele, pokud vozidlo nemá vlastní)
# ----------------------------------------------------------------------

KIND_OPTIONS = [("", "Všechna vozidla"), ("car", "Auta"), ("moto", "Motorky")]


def _read_default_interval(form):
    data = {
        "service_type": form.str("service_type", "Typ servisu", required=True, max_len=50),
        "vehicle_kind": form.str("vehicle_kind", "Pro vozidla"),
        "interval_months": form.int("interval_months", "Interval (měsíce)", min_value=1, max_value=240),
        "interval_km": form.int("interval_km", "Interval (km)", min_value=1),
    }
    form.check()
    return data


def _defaults_page(request, db, user, values=None, interval=None, error=None, status_code=200):
    service = DefaultIntervalService(db)
    return render(request, "maintenance/default_intervals.html", status_code=status_code,
                  intervals=service.list_for_user(user.id), interval=interval, values=values or {},
                  kind_options=KIND_OPTIONS, service_types=SERVICE_TYPES, error=error)


@router.get("/service-intervals")
async def default_intervals(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return _defaults_page(request, db, user)


@router.post("/service-intervals")
async def default_interval_add(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    form = FormReader(await request.form())
    try:
        DefaultIntervalService(db).create(user.id, _read_default_interval(form))
    except ValidationError as e:
        db.rollback()
        return _defaults_page(request, db, user, form.values, error=str(e), status_code=400)
    flash(request, "Univerzální interval byl přidán.")
    return RedirectResponse("/service-intervals", status_code=303)


@router.post("/service-intervals/suggested")
async def default_interval_suggested(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    DefaultIntervalService(db).add_suggested(user.id)
    flash(request, "Doporučené intervaly byly přidány – upravte si je podle vozidel.")
    return RedirectResponse("/service-intervals", status_code=303)


@router.get("/service-intervals/{interval_id}/edit")
async def default_interval_edit(request: Request, interval_id: int, user=Depends(get_current_user),
                                db=Depends(get_db)):
    interval = DefaultIntervalService(db).get(interval_id, user.id)
    values = {"service_type": interval.service_type, "vehicle_kind": interval.vehicle_kind or "",
              "interval_months": iso(interval.interval_months), "interval_km": iso(interval.interval_km)}
    return _defaults_page(request, db, user, values, interval)


@router.post("/service-intervals/{interval_id}/edit")
async def default_interval_edit_post(request: Request, interval_id: int, user=Depends(get_current_user),
                                     db=Depends(get_db)):
    service = DefaultIntervalService(db)
    interval = service.get(interval_id, user.id)
    form = FormReader(await request.form())
    try:
        service.update(interval, _read_default_interval(form))
    except ValidationError as e:
        db.rollback()
        return _defaults_page(request, db, user, form.values, interval, str(e), 400)
    flash(request, "Změny byly uloženy.")
    return RedirectResponse("/service-intervals", status_code=303)


@router.post("/service-intervals/{interval_id}/delete")
async def default_interval_delete(request: Request, interval_id: int, user=Depends(get_current_user),
                                  db=Depends(get_db)):
    service = DefaultIntervalService(db)
    service.delete(service.get(interval_id, user.id))
    flash(request, "Univerzální interval byl odstraněn.")
    return RedirectResponse("/service-intervals", status_code=303)


# ======================================================================
# Upomínky
# ======================================================================

def _read_reminder(form):
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "title": form.str("title", "Název", required=True, max_len=100),
        "due_date": form.date("due_date", "Datum"),
        "due_odometer": form.int("due_odometer", "Stav tachometru", min_value=0),
        "repeat": form.choice("repeat", "Opakování", REPEAT_OPTIONS, default="none"),
        "repeat_km": form.int("repeat_km", "Opakovat po km", min_value=1),
        "notify_days_before": form.int("notify_days_before", "Upozornit dní předem", min_value=0, max_value=365),
        "notify_km_before": form.int("notify_km_before", "Upozornit km předem", min_value=0),
        "note": form.str("note", "Poznámka"),
        "is_done": form.bool("is_done"),
    }
    form.check()
    return data


def _reminder_values(r):
    return {
        "vehicle_id": str(r.vehicle_id), "title": r.title, "due_date": iso(r.due_date),
        "due_odometer": iso(r.due_odometer), "repeat": r.repeat, "repeat_km": iso(r.repeat_km),
        "notify_days_before": iso(r.notify_days_before), "notify_km_before": iso(r.notify_km_before),
        "note": r.note or "", "is_done": "on" if r.is_done else "",
    }


register_crud(router, CrudConfig(
    prefix="/reminders",
    service_cls=ReminderService,
    template="maintenance/reminder_form.html",
    read_form=_read_reminder,
    to_values=_reminder_values,
    default_values=lambda vid: {"repeat": "none", "notify_days_before": "14", "notify_km_before": "500"},
    extra_context=lambda db, user: {"repeat_options": REPEAT_OPTIONS},
    messages={"created": "Upomínka byla uložena.", "deleted": "Upomínka byla smazána."},
))


@router.get("/reminders")
async def list_reminders(request: Request, show: str = "open", user=Depends(get_current_user), db=Depends(get_db)):
    vehicles = visible_vehicles(db, user)
    ids = [v.id for v in vehicles]
    vehicle_service = VehicleService(db)
    service = ReminderService(db)
    odometers = {vid: vehicle_service.get_current_odometer(vid) for vid in ids}
    reminders = [(r, service.get_status(r, odometers[r.vehicle_id]))
                 for r in service.list_for_vehicles(ids, include_done=(show == "all"))]
    return render(request, "maintenance/reminder_list.html", reminders=reminders, show=show,
                  repeat_options=REPEAT_OPTIONS,
                  editable_ids=set(vehicle_service.get_accessible_ids(user, ROLE_EDITOR)))


@router.post("/reminders/{record_id}/done")
async def reminder_done(request: Request, record_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = ReminderService(db)
    reminder = service.get(record_id)
    vehicle = check_record_access(db, user, reminder, ROLE_EDITOR)
    service.complete(reminder, VehicleService(db).get_current_odometer(vehicle.id))
    if reminder.is_done:
        flash(request, f"Upomínka „{reminder.title}“ byla vyřízena.")
    else:
        flash(request, f"Upomínka „{reminder.title}“ byla posunuta na další termín.")
    next_url = (await request.form()).get("next") or ""
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = f"/vehicles/{vehicle.id}"
    return RedirectResponse(next_url, status_code=303)


@router.post("/reminders/{record_id}/reopen")
async def reminder_reopen(request: Request, record_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = ReminderService(db)
    reminder = service.get(record_id)
    check_record_access(db, user, reminder, ROLE_EDITOR)
    service.reopen(reminder)
    flash(request, "Upomínka byla znovu otevřena.")
    return RedirectResponse("/reminders?show=all", status_code=303)


# ======================================================================
# Výdaje
# ======================================================================

def _read_expense(form):
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "expense_date": form.date("expense_date", "Datum", required=True),
        "category": form.str("category", "Kategorie", required=True, max_len=30),
        "description": form.str("description", "Popis", max_len=200),
        "odometer": form.int("odometer", "Stav tachometru", min_value=0),
        "price_paid": form.decimal("price_paid", "Částka", required=True, min_value=0),
        "currency_code": form.str("currency_code", "Měna") or "CZK",
        "manual_rate": form.decimal("manual_rate", "Kurz", positive=True),
        "note": form.str("note", "Poznámka"),
        "valid_from": form.date("valid_from", "Platnost od"),
        "valid_until": form.date("valid_until", "Platnost do"),
        "remind": form.bool("remind"),
        "insurance_claim": form.bool("insurance_claim"),
        "insurer": form.str("insurer", "Pojišťovna", max_len=100),
        "policy_number": form.str("policy_number", "Číslo pojistky", max_len=50),
        "claim_number": form.str("claim_number", "Číslo pojistné události", max_len=50),
        "insurance_paid": form.decimal("insurance_paid", "Uhradila pojišťovna", min_value=0),
    }
    if data["category"] == VIGNETTE_CATEGORY:
        data["vignette_variant"] = form.choice("vignette_variant", "Typ známky", VIGNETTE_VARIANTS)
    form.check()
    return data


def _expense_values(e):
    return {
        "vehicle_id": str(e.vehicle_id), "expense_date": iso(e.expense_date), "category": e.category,
        "description": e.description or "", "odometer": iso(e.odometer), "price_paid": iso(e.price_paid),
        "currency_code": e.currency_code, "manual_rate": rate_from_record(e), "note": e.note or "",
        "valid_from": iso(e.valid_from), "valid_until": iso(e.valid_until),
        "remind": "on" if e.reminder_id else "", "vignette_variant": _guess_variant(e),
        **_insurance_values(e),
    }


def _guess_variant(e):
    """Typ známky u uloženého výdaje (podle délky platnosti), jinak vlastní platnost."""
    if e.category != VIGNETTE_CATEGORY or not (e.valid_from and e.valid_until):
        return ""
    days = (e.valid_until - e.valid_from).days + 1
    return next((key for key, (_, length) in VIGNETTE_VARIANTS.items() if length == days), "")


def _expense_defaults(vehicle_id):
    today = date.today().isoformat()
    return {"expense_date": today, "currency_code": "CZK", "remind": "on", "valid_from": today}


register_crud(router, CrudConfig(
    prefix="/expenses",
    service_cls=ExpenseService,
    template="maintenance/expense_form.html",
    read_form=_read_expense,
    to_values=_expense_values,
    default_values=_expense_defaults,
    extra_context=lambda db, user: {
        "categories": EXPENSE_CATEGORIES, "validity_categories": VALIDITY_CATEGORIES,
        "vignette_category": VIGNETTE_CATEGORY,
        "vignette_variants": {key: label for key, (label, _) in VIGNETTE_VARIANTS.items()},
        "vignette_days": {key: days for key, (_, days) in VIGNETTE_VARIANTS.items()},
    },
    messages={"created": "Výdaj byl uložen.", "deleted": "Výdaj byl smazán."},
    prefill_params=("category", "valid_from"),
))


@router.get("/expenses")
async def list_expenses(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    vehicles, ids, date_from, date_to, filters = _list_filters(request, db, user)
    records = ExpenseService(db).search(ids, date_from, date_to, category=filters["category"])
    by_category = {}
    for r in records:
        by_category[r.category] = by_category.get(r.category, 0) + (r.own_cost or 0)
    return render(request, "maintenance/expense_list.html", vehicles=vehicles, records=records, filters=filters,
                  total=sum(by_category.values(), 0),
                  by_category=sorted(by_category.items(), key=lambda kv: -kv[1]),
                  categories=EXPENSE_CATEGORIES,
                  editable_ids=set(VehicleService(db).get_accessible_ids(user, ROLE_EDITOR)))


@router.get("/expenses/export.csv")
async def export_expenses(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    _, ids, date_from, date_to, filters = _list_filters(request, db, user)
    records = ExpenseService(db).search(ids, date_from, date_to, category=filters["category"])
    rows = [(r.vehicle.display_name, r.expense_date, r.category, r.description, r.odometer,
             decimal_csv(r.price_paid), r.currency_code, decimal_csv(r.price_local),
             decimal_csv(r.insurance_paid), r.insurer, r.note) for r in records]
    return csv_response("vydaje.csv", ["Vozidlo", "Datum", "Kategorie", "Popis", "Tachometr", "Částka", "Měna",
                                       "Částka CZK", "Uhradila pojišťovna", "Pojišťovna", "Poznámka"], rows)


# ======================================================================
# Přehled upozornění (pro dashboard)
# ======================================================================

def alerts_for_user(db, user):
    vehicles = VehicleService(db).get_vehicles_for_user(user, only_active=True)
    return collect_alerts(db, vehicles)


# ======================================================================
# Poznámky k vozidlu (garáž, půjčeno, nehoda…) - zobrazují se na časové ose
# ======================================================================

def _read_note(form):
    from datetime import datetime, time
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "note_date": form.date("note_date", "Datum", required=True),
        "note_time": form.time("note_time", "Čas"),
        "odometer": form.int("odometer", "Stav tachometru", min_value=0),
        "category": form.str("category", "Typ", max_len=40),
        "text": form.str("text", "Poznámka", max_len=5000),
    }
    form.check()
    return {
        "vehicle_id": data["vehicle_id"],
        "note_datetime": datetime.combine(data["note_date"], data["note_time"] or time(12, 0)),
        "odometer": data["odometer"], "category": data["category"], "text": data["text"],
    }


def _note_values(n):
    return {
        "vehicle_id": str(n.vehicle_id), "note_date": n.note_datetime.date().isoformat(),
        "note_time": n.note_datetime.strftime("%H:%M"), "odometer": iso(n.odometer),
        "category": n.category or "", "text": n.text or "",
    }


def _note_defaults(vehicle_id):
    from datetime import datetime
    now = datetime.now()
    return {"note_date": now.date().isoformat(), "note_time": now.strftime("%H:%M")}


register_crud(router, CrudConfig(
    prefix="/notes",
    service_cls=VehicleNoteService,
    template="maintenance/note_form.html",
    read_form=_read_note,
    to_values=_note_values,
    default_values=_note_defaults,
    extra_context=lambda db, user: {
        "note_categories": VehicleNoteService(db).get_categories(
            VehicleService(db).get_accessible_ids(user)),
    },
    messages={"created": "Poznámka byla uložena.", "updated": "Poznámka byla upravena.",
              "deleted": "Poznámka byla smazána."},
    prefill_params=("category",),
    track_author=True,
))
