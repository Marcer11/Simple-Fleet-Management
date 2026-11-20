from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from models.fuel_record import PAYMENT_METHODS
from models.vehicle import ROLE_EDITOR
from services import timeline
from services.errors import ValidationError, NotFoundError
from services.fuel_record_service import FuelRecordService
from services.fuel_type_service import FuelTypeService
from services.pricing import fuel_prices
from services.stations import station_overview
from services.vehicle_service import VehicleService
from web.common import (
    editable_vehicles, visible_vehicles, check_record_access, flash_vehicle_alerts,
    default_filter_period, csv_response, decimal_csv, COMMON_CURRENCIES,
)
from web.deps import get_db, get_current_user, flash, render
from web.forms import FormReader, iso, parse_filter_date, parse_filter_int, rate_from_record

router = APIRouter(prefix="/fuel-records")


def _filters(request, db, user):
    q = request.query_params
    vehicles = visible_vehicles(db, user)
    vehicle_id = parse_filter_int(q.get("vehicle_id"))
    ids = [v.id for v in vehicles if vehicle_id in (None, v.id)]
    if q.get("all"):
        date_from = date_to = None
    else:
        date_from, date_to = default_filter_period(parse_filter_date(q.get("date_from")),
                                                   parse_filter_date(q.get("date_to")))
    fuel_type = q.get("fuel_type") or None
    filters = {"vehicle_id": vehicle_id, "date_from": iso(date_from), "date_to": iso(date_to),
               "fuel_type": fuel_type or "", "all": q.get("all", "")}
    records = FuelRecordService(db).search(ids, date_from, date_to, fuel_type)
    return vehicles, records, filters


@router.get("")
async def list_fuel_records(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    vehicles, records, filters = _filters(request, db, user)
    totals = {
        "price": sum((r.price_local or 0 for r in records), 0),
        "count": len(records),
    }
    return render(request, "fuel/list.html", vehicles=vehicles, records=records, filters=filters,
                  totals=totals, fuel_types=_filter_fuel_types(db, user, vehicles, filters["fuel_type"]),
                  editable_ids=set(VehicleService(db).get_accessible_ids(user, ROLE_EDITOR)))


def _filter_fuel_types(db, user, vehicles, selected):
    """Paliva pro filtr: vlastní seznam + paliva zapsaná u viditelných vozidel."""
    names = FuelTypeService(db).names(user)
    known = {n.lower() for n in names}
    used = FuelRecordService(db).get_used_values([v.id for v in vehicles], "fuel_type")
    extra = [n for n in used + ([selected] if selected else []) if n.lower() not in known]
    return names + sorted(set(extra))


@router.get("/export.csv")
async def export_fuel_records(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    _, records, _ = _filters(request, db, user)
    rows = [
        (r.vehicle.display_name, r.refuel_datetime.strftime("%d.%m.%Y %H:%M"), r.odometer, r.fuel_type,
         decimal_csv(r.volume_liters), decimal_csv(r.unit_price), decimal_csv(r.price_paid), r.currency_code,
         decimal_csv(r.price_local), r.payment_method, r.station_name, r.station_address, "ano" if r.full_tank else "",
         "ano" if r.skipped_refuel else "", decimal_csv(r.consumption), r.note)
        for r in records
    ]
    header = ["Vozidlo", "Datum a čas", "Tachometr", "Palivo", "Množství", "Cena/jedn.", "Cena", "Měna",
              "Cena CZK", "Platba", "Stanice", "Adresa stanice", "Plná", "Vynecháno", "Spotřeba", "Poznámka"]
    return csv_response("tankovani.csv", header, rows)


@router.get("/stations")
async def stations(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    """Přehled čerpacích stanic: značka -> konkrétní stanice, počet tankování a útrata."""
    vehicles, records, filters = _filters(request, db, user)
    overview = station_overview(records)
    totals = {"count": len(records), "cost": sum((r.price_local or 0 for r in records), 0),
              "brands": len(overview), "stations": sum(len(b["stations"]) for b in overview)}
    return render(request, "fuel/stations.html", vehicles=vehicles, filters=filters,
                  overview=overview, totals=totals)


@router.get("/timeline-stop")
async def timeline_stop(request: Request, user=Depends(get_current_user)):
    """Dohledá v Timeline pumpu podle data a času tankování (klíč přihlášeného uživatele)."""
    def reply(status, **data):
        # osobní údaje (poloha) - nic necachovat
        return JSONResponse({"status": status, **data}, headers={"Cache-Control": "no-store"})

    if not timeline.is_enabled():
        return reply("error", message="Napojení na Timeline není nastaveno.")
    if not user.timeline_api_key:
        return reply("no_key", message="Nejdřív si v profilu uložte API klíč Timeline.")
    try:
        at = datetime.combine(date.fromisoformat(request.query_params.get("date", "")),
                              time.fromisoformat(request.query_params.get("time", "")))
    except ValueError:
        return reply("error", message="Vyplňte datum a čas tankování.")
    try:
        stop = timeline.find_fuel_stop(user.timeline_api_key, at)
    except timeline.TimelineError as e:
        return reply("no_key" if e.kind == "auth" else "error", message=str(e))
    if stop is None:
        return reply("not_found", message="V Timeline jste v tu dobu u čerpací stanice nebyl/a.")
    return reply("found", **stop)


def _form_context(db, user, record=None):
    vehicles = editable_vehicles(db, user)
    ids = [v.id for v in vehicles]
    service = FuelRecordService(db)
    last_records = {v.id: service.get_last_record(v.id) for v in vehicles}
    return {
        "record": record,
        "vehicles": vehicles,
        "fuel_types": FuelTypeService(db).names(user),
        "payment_methods": PAYMENT_METHODS,
        "currencies": COMMON_CURRENCIES,
        "stations": service.get_used_values(ids, "station_name"),
        "last_odometers": {v.id: VehicleService(db).get_current_odometer(v.id) for v in vehicles},
        "last_fuel_types": {vid: (r.fuel_type if r else "") for vid, r in last_records.items()},
        "timeline_enabled": timeline.is_enabled(),
        "timeline_ready": timeline.is_enabled() and bool(user.timeline_api_key),
    }


def _read_form(form):
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "refuel_date": form.date("refuel_date", "Datum", required=True),
        "refuel_time": form.time("refuel_time", "Čas", required=True),
        "odometer": form.int("odometer", "Stav tachometru", required=True, min_value=0),
        "fuel_type": form.str("fuel_type", "Palivo", required=True, max_len=30),
        "volume": form.decimal("volume_liters", "Množství", required=True, positive=True),
        "unit_price": form.decimal("unit_price", "Cena za jednotku", min_value=0),
        "total_price": form.decimal("price_paid", "Celková cena", min_value=0),
        "currency_code": form.str("currency_code", "Měna") or "CZK",
        "manual_rate": form.decimal("manual_rate", "Kurz", positive=True),
        "payment_method": form.str("payment_method", "Platba", max_len=20),
        "station_name": form.str("station_name", "Čerpací stanice", max_len=100),
        "station_address": form.str("station_address", "Adresa stanice", max_len=200),
        "full_tank": form.bool("full_tank"),
        "skipped_refuel": form.bool("skipped_refuel"),
        "note": form.str("note", "Poznámka"),
    }
    form.check()
    if data["refuel_date"] > date.today():
        raise ValidationError("Datum tankování nemůže být v budoucnosti.")
    prices = fuel_prices(data["volume"], data["unit_price"], data["total_price"], data["currency_code"],
                         data["refuel_date"], data["manual_rate"])
    return {
        "vehicle_id": data["vehicle_id"],
        "refuel_datetime": datetime.combine(data["refuel_date"], data["refuel_time"]),
        "odometer": data["odometer"],
        "fuel_type": data["fuel_type"],
        "volume_liters": data["volume"],
        **prices,
        "payment_method": data["payment_method"],
        "station_name": data["station_name"],
        "station_address": data["station_address"],
        "full_tank": data["full_tank"],
        "skipped_refuel": data["skipped_refuel"],
        "note": data["note"],
    }


@router.get("/add")
async def add_form(request: Request, vehicle_id: int = None, user=Depends(get_current_user), db=Depends(get_db)):
    context = _form_context(db, user)
    if vehicle_id is None and len(context["vehicles"]) == 1:
        vehicle_id = context["vehicles"][0].id
    now = datetime.now()
    values = {
        "vehicle_id": str(vehicle_id or ""),
        "refuel_date": now.date().isoformat(),
        "refuel_time": now.strftime("%H:%M"),
        "currency_code": "CZK",
        "full_tank": "on",
        "fuel_type": context["last_fuel_types"].get(vehicle_id, "") if vehicle_id else "",
    }
    return render(request, "fuel/form.html", values=values, **context)


@router.post("/add")
async def add_post(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    form = FormReader(await request.form())
    vehicle_service = VehicleService(db)
    try:
        data = _read_form(form)
        data["fuel_type"], data["fuel_category"] = FuelTypeService(db).resolve(user, data["fuel_type"])
        vehicle = vehicle_service.get_vehicle_for_user(data["vehicle_id"], user, ROLE_EDITOR)
        record = FuelRecordService(db).create_fuel_record(**data, created_by_id=user.id)
    except (ValidationError, NotFoundError) as e:
        db.rollback()
        return render(request, "fuel/form.html", status_code=400, values=form.values, error=str(e),
                      **_form_context(db, user))
    message = "Tankování bylo uloženo."
    if record.consumption is not None:
        message += f" Spotřeba: {str(record.consumption).replace('.', ',')} {record.unit}/100 km."
    flash(request, message)
    flash_vehicle_alerts(request, db, vehicle)
    if form.raw.get("next") == "add":
        return RedirectResponse(f"/fuel-records/add?vehicle_id={vehicle.id}", status_code=303)
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.get("/{record_id}/edit")
async def edit_form(request: Request, record_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    record = FuelRecordService(db).get_fuel_record(record_id)
    check_record_access(db, user, record, ROLE_EDITOR)
    values = {
        "vehicle_id": str(record.vehicle_id),
        "refuel_date": record.refuel_datetime.date().isoformat(),
        "refuel_time": record.refuel_datetime.strftime("%H:%M"),
        "odometer": str(record.odometer),
        "fuel_type": record.fuel_type,
        "volume_liters": iso(record.volume_liters),
        "unit_price": iso(record.unit_price),
        "price_paid": iso(record.price_paid),
        "currency_code": record.currency_code,
        "manual_rate": rate_from_record(record),
        "payment_method": record.payment_method or "",
        "station_name": record.station_name or "",
        "station_address": record.station_address or "",
        "full_tank": "on" if record.full_tank else "",
        "skipped_refuel": "on" if record.skipped_refuel else "",
        "note": record.note or "",
    }
    return render(request, "fuel/form.html", values=values, **_form_context(db, user, record))


@router.post("/{record_id}/edit")
async def edit_post(request: Request, record_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = FuelRecordService(db)
    record = service.get_fuel_record(record_id)
    check_record_access(db, user, record, ROLE_EDITOR)
    form = FormReader(await request.form())
    try:
        data = _read_form(form)
        data["fuel_type"], data["fuel_category"] = FuelTypeService(db).resolve(user, data["fuel_type"])
        # při přesunu na jiné vozidlo musí mít uživatel právo i k cílovému vozidlu
        vehicle = VehicleService(db).get_vehicle_for_user(data["vehicle_id"], user, ROLE_EDITOR)
        service.update_fuel_record(record, data)
    except (ValidationError, NotFoundError) as e:
        db.rollback()
        return render(request, "fuel/form.html", status_code=400, values=form.values, error=str(e),
                      **_form_context(db, user, record))
    flash(request, "Tankování bylo upraveno.")
    flash_vehicle_alerts(request, db, vehicle)
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{record_id}/delete")
async def delete_post(request: Request, record_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = FuelRecordService(db)
    record = service.get_fuel_record(record_id)
    vehicle = check_record_access(db, user, record, ROLE_EDITOR)
    service.delete_fuel_record(record)
    flash(request, "Tankování bylo smazáno.")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)
