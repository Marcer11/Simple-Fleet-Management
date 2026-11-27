from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from models.vehicle import ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER, ROLE_LEVELS, SHARE_ROLES
from services.errors import ValidationError
from services.events import collect_events
from services.tire_service import TireSwapService, TireTreadCheckService, mounted_seasons, open_mounts
from models import TireDefect
from services.fuel_record_service import FuelRecordService
from services.maintenance_service import (
    ServiceIntervalService, ServiceRecordService, ReminderService, ExpenseService, VehicleNoteService,
    collect_alerts,
)
from services.insights import insights, year_overview
from services.stats_service import StatsService
from services.vehicle_service import VehicleService
from web.deps import get_db, get_current_user, flash, render
from web.forms import FormReader, iso
from web.routers.stats import parse_period

router = APIRouter(prefix="/vehicles")


def _vehicle_values(vehicle):
    return {
        "brand": vehicle.brand, "model": vehicle.model, "kind": vehicle.kind or "car",
        "production_year": iso(vehicle.production_year),
        "engine_volume": iso(vehicle.engine_volume), "engine_power": iso(vehicle.engine_power),
        "license_plate": vehicle.license_plate or "", "vin": vehicle.vin or "",
        "color": vehicle.color or "", "color_hex": vehicle.color_hex or "#FFFFFF",
        "purchase_date": iso(vehicle.purchase_date), "sale_date": iso(vehicle.sale_date),
        "note": vehicle.note or "", "is_active": "on" if vehicle.is_active else "",
        "purchase_price": iso(vehicle.purchase_price), "sale_price": iso(vehicle.sale_price),
        "tire_sizes": vehicle.tire_sizes or "", "is_rental": "on" if vehicle.is_rental else "",
        "lender": vehicle.lender or "",
        "fuel": vehicle.fuel or "", "alt_fuel": vehicle.alt_fuel or "",
        "purchase_odometer": iso(vehicle.purchase_odometer), "sale_odometer": iso(vehicle.sale_odometer),
    }


def _read_vehicle_form(form):
    data = {
        "brand": form.str("brand", "Značka", required=True, max_len=50),
        "model": form.str("model", "Model", required=True, max_len=50),
        "kind": form.str("kind", "Druh") or "car",
        "production_year": form.int("production_year", "Rok výroby", min_value=1901,
                                    max_value=date.today().year + 1),
        "engine_volume": form.int("engine_volume", "Objem motoru", min_value=0, max_value=20_000),
        "engine_power": form.int("engine_power", "Výkon", min_value=0, max_value=2_000),
        "license_plate": form.str("license_plate", "SPZ", max_len=12),
        "vin": form.str("vin", "VIN", max_len=20),
        "color": form.str("color", "Barva", max_len=30),
        "color_hex": form.str("color_hex", "Barva (HEX)") or "#FFFFFF",
        "purchase_date": form.date("purchase_date", "Datum nákupu"),
        "sale_date": form.date("sale_date", "Datum prodeje"),
        "purchase_price": form.decimal("purchase_price", "Pořizovací cena", min_value=0),
        "sale_price": form.decimal("sale_price", "Prodejní cena", min_value=0),
        "purchase_odometer": form.int("purchase_odometer", "Km při nákupu", min_value=0),
        "sale_odometer": form.int("sale_odometer", "Km při prodeji", min_value=0),
        "note": form.str("note", "Poznámka"),
        "tire_sizes": form.str("tire_sizes", "Rozměry pneumatik", max_len=500),
        "is_rental": form.bool("is_rental"),
        "lender": form.str("lender", "Koho auto je", max_len=100),
        "fuel": form.str("fuel", "Palivo"),
        "alt_fuel": form.str("alt_fuel", "Alternativní palivo"),
    }
    form.check()
    return data


# ----------------------------------------------------------------------
# Seznam a přidání
# ----------------------------------------------------------------------

@router.get("")
async def list_vehicles(request: Request, show: str = "all", user=Depends(get_current_user), db=Depends(get_db)):
    """Výchozí jsou všechna vozidla seřazená podle posledního záznamu (nejnovější nahoře)."""
    service = VehicleService(db)
    vehicles = service.get_vehicles_for_user(user, only_active=(show == "active"))
    last_dates = service.last_record_dates(vehicles)
    vehicles.sort(key=lambda v: (last_dates[v.id] is not None, last_dates[v.id] or date.min), reverse=True)
    roles = service.get_roles_for_user(user)
    odometers = {v.id: service.get_current_odometer(v.id) for v in vehicles}
    stats = StatsService(db)
    consumption = {v.id: stats.avg_consumption(v.id) for v in vehicles}
    year_costs = stats.year_costs([v.id for v in vehicles], date.today().year)
    inactive_count = len(service.get_vehicles_for_user(user)) - len(service.get_vehicles_for_user(user, True))
    alerts = {}
    for alert in collect_alerts(db, [v for v in vehicles if v.in_use]):
        alerts.setdefault(alert.vehicle.id, []).append(alert)
    return render(request, "vehicles/list.html", vehicles=vehicles, roles=roles, odometers=odometers,
                  consumption=consumption, year_costs=year_costs, last_dates=last_dates,
                  vignettes=service.vignette_status(vehicles), alerts=alerts,
                  show=show, inactive_count=inactive_count, tires=mounted_seasons(db, [v.id for v in vehicles]))


def _lenders(db, user):
    """Půjčovny / lidé, od kterých už uživatel auto měl (nabídka ve formuláři)."""
    return sorted({v.lender for v in VehicleService(db).get_vehicles_for_user(user) if v.lender}, key=str.lower)


@router.get("/add")
async def add_vehicle_form(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return render(request, "vehicles/form.html", vehicle=None, values={"color_hex": "#FFFFFF", "kind": "car"},
                  lenders=_lenders(db, user))


@router.post("/add")
async def add_vehicle_post(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    form = FormReader(await request.form())
    try:
        data = _read_vehicle_form(form)
        vehicle = VehicleService(db).create_vehicle(owner_id=user.id, **data)
    except ValidationError as e:
        return render(request, "vehicles/form.html", status_code=400, vehicle=None, values=form.values, error=str(e),
                      lenders=_lenders(db, user))
    flash(request, f"Vozidlo {vehicle.display_name} bylo přidáno.")
    if vehicle.is_rental:  # u půjčeného vozidla rovnou zápis půjčení
        return RedirectResponse(f"/rentals/add?vehicle_id={vehicle.id}", status_code=303)
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


# ----------------------------------------------------------------------
# Detail, úprava, smazání
# ----------------------------------------------------------------------

# Záložky detailu vozidla (klíč -> popisek); Statistiky mají vlastní adresu
VEHICLE_TABS = {"": "Přehled", "detail": "Údaje", "fuel": "Tankování", "service": "Servis",
                "expenses": "Výdaje", "notes": "Poznámky", "tires": "Pneumatiky"}
LEVEL_ORDER = {"overdue": 0, "warning": 1, "ok": 2, "unknown": 3}


def vehicle_head(db, vehicle, role):
    """Společné údaje hlavičky vozidla (detail i statistiky)."""
    return {"vehicle": vehicle, "role": role, "vehicle_tabs": VEHICLE_TABS,
            "can_edit": ROLE_LEVELS[role] >= ROLE_LEVELS[ROLE_EDITOR], "is_owner": role == ROLE_OWNER,
            "tire_seasons": mounted_seasons(db, [vehicle.id]).get(vehicle.id)}


def _intervals_and_reminders(db, vehicle, odometer):
    interval_service = ServiceIntervalService(db)
    reminder_service = ReminderService(db)
    intervals = [(i, interval_service.get_status(i, odometer))
                 for i in interval_service.effective_for_vehicles([vehicle], only_active=False)]
    reminders = [(r, reminder_service.get_status(r, odometer))
                 for r in reminder_service.list_for_vehicles([vehicle.id])]
    return intervals, reminders


@router.get("/{vehicle_id}")
async def vehicle_detail(request: Request, vehicle_id: int, tab: str = "", user=Depends(get_current_user),
                         db=Depends(get_db)):
    service = VehicleService(db)
    vehicle = service.get_vehicle_for_user(vehicle_id, user)
    role = service.get_role(vehicle, user)
    tab = tab if tab in VEHICLE_TABS else ""
    odometer = service.get_current_odometer(vehicle.id)
    stats = StatsService(db)
    ids = [vehicle.id]
    context = {**vehicle_head(db, vehicle, role), "tab": tab, "odometer": odometer,
               "editable_ids": set(ids) if ROLE_LEVELS[role] >= ROLE_LEVELS[ROLE_EDITOR] else set()}
    year_start = date(date.today().year, 1, 1)

    if tab == "":
        intervals, reminders = _intervals_and_reminders(db, vehicle, odometer)
        due = sorted(((i, s) for i, s in intervals + reminders
                      if getattr(i, "is_active", True) and s.level in ("overdue", "warning", "ok")),
                     key=lambda x: (LEVEL_ORDER[x[1].level], x[1].days_left if x[1].days_left is not None else 99999))
        fuel_service = FuelRecordService(db)
        fuel_year = fuel_service.search(ids, year_start)
        services = ServiceRecordService(db).search(ids)
        expenses_year = ExpenseService(db).search(ids, year_start)
        context.update(
            alerts=collect_alerts(db, [vehicle]),
            avg_consumption=stats.avg_consumption(vehicle.id),
            profile=stats.usage_profile(vehicle.id),
            year_cost=stats.year_costs(ids, date.today().year).get(vehicle.id),
            last_fuel=next(iter(fuel_service.search(ids, limit=1)), None),
            fuel_year={"count": len(fuel_year), "cost": sum((r.price_local or 0 for r in fuel_year), 0)},
            last_service=services[0] if services else None, next_due=due[0] if due else None,
            services_year=sum((r.own_cost or 0 for r in services if r.service_date >= year_start), 0),
            expenses_year={"count": len(expenses_year), "cost": sum((r.own_cost or 0 for r in expenses_year), 0)},
            validities=ExpenseService(db).current_validities(vehicle.id),
            mounted_tires=open_mounts(db, vehicle.id),
            events=collect_events(db, [vehicle], limit=15),
        )
    elif tab == "detail":
        context.update(validities=ExpenseService(db).current_validities(vehicle.id),
                       profile=stats.usage_profile(vehicle.id), owner=vehicle.owner, rentals=list(vehicle.rentals))
    elif tab == "fuel":
        records = FuelRecordService(db).search(ids)
        context.update(records=records, breakdown=stats.fuel_breakdown(vehicle.id),
                       totals={"count": len(records), "price": sum((r.price_local or 0 for r in records), 0)},
                       avg_consumption=stats.avg_consumption(vehicle.id))
    elif tab == "service":
        intervals, reminders = _intervals_and_reminders(db, vehicle, odometer)
        records = ServiceRecordService(db).search(ids)
        context.update(intervals=intervals, reminders=reminders, records=records,
                       total=sum((r.price_local or 0 for r in records), 0))
    elif tab == "expenses":
        records = ExpenseService(db).search(ids)
        by_category = {}
        for r in records:
            by_category[r.category] = by_category.get(r.category, 0) + (r.own_cost or 0)
        context.update(records=records, total=sum((r.price_local or 0 for r in records), 0),
                       by_category=sorted(by_category.items(), key=lambda kv: -kv[1]),
                       validities=ExpenseService(db).current_validities(vehicle.id))
    elif tab == "notes":
        context.update(notes=VehicleNoteService(db).search(ids))
    elif tab == "tires":
        context.update(mounted_tires=open_mounts(db, vehicle.id), swaps=TireSwapService(db).for_vehicles(ids),
                       checks=TireTreadCheckService(db).for_vehicles(ids),
                       defects=(db.query(TireDefect).filter(TireDefect.vehicle_id == vehicle.id)
                                .order_by(TireDefect.defect_date.desc(), TireDefect.id.desc()).all()),
                       can_delete_swap={})
    return render(request, "vehicles/detail.html", **context)


@router.get("/{vehicle_id}/edit")
async def edit_vehicle_form(request: Request, vehicle_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    vehicle = VehicleService(db).get_vehicle_for_user(vehicle_id, user, ROLE_EDITOR)
    return render(request, "vehicles/form.html", vehicle=vehicle, values=_vehicle_values(vehicle),
                  is_owner=vehicle.owner_id == user.id, lenders=_lenders(db, user))


@router.post("/{vehicle_id}/edit")
async def edit_vehicle_post(request: Request, vehicle_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = VehicleService(db)
    vehicle = service.get_vehicle_for_user(vehicle_id, user, ROLE_EDITOR)
    form = FormReader(await request.form())
    try:
        service.update_vehicle(vehicle, _read_vehicle_form(form))
    except ValidationError as e:
        db.rollback()
        return render(request, "vehicles/form.html", status_code=400, vehicle=vehicle, values=form.values,
                      error=str(e), is_owner=vehicle.owner_id == user.id, lenders=_lenders(db, user))
    flash(request, "Změny byly uloženy.")
    return RedirectResponse(f"/vehicles/{vehicle_id}", status_code=303)


@router.post("/{vehicle_id}/activate")
async def activate_vehicle(request: Request, vehicle_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = VehicleService(db)
    vehicle = service.get_vehicle_for_user(vehicle_id, user, ROLE_EDITOR)
    service.update_vehicle(vehicle, {"is_active": True})
    flash(request, "Vozidlo bylo aktivováno.")
    return RedirectResponse(f"/vehicles/{vehicle_id}?tab=detail", status_code=303)


@router.post("/{vehicle_id}/deactivate")
async def deactivate_vehicle(request: Request, vehicle_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = VehicleService(db)
    vehicle = service.get_vehicle_for_user(vehicle_id, user, ROLE_EDITOR)
    service.update_vehicle(vehicle, {"is_active": False})
    flash(request, "Vozidlo bylo deaktivováno.")
    return RedirectResponse(f"/vehicles/{vehicle_id}?tab=detail", status_code=303)


@router.post("/{vehicle_id}/delete")
async def delete_vehicle(request: Request, vehicle_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = VehicleService(db)
    vehicle = service.get_vehicle_for_user(vehicle_id, user, ROLE_OWNER)
    name = vehicle.display_name
    service.delete_vehicle(vehicle.id)
    flash(request, f"Vozidlo {name} bylo smazáno včetně všech záznamů.")
    return RedirectResponse("/vehicles", status_code=303)


# ----------------------------------------------------------------------
# Sdílení
# ----------------------------------------------------------------------

@router.get("/{vehicle_id}/sharing")
async def sharing(request: Request, vehicle_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = VehicleService(db)
    vehicle = service.get_vehicle_for_user(vehicle_id, user, ROLE_OWNER)
    return render(request, "vehicles/sharing.html", vehicle=vehicle, shares=service.get_shares(vehicle),
                  share_roles=SHARE_ROLES, values={"role": ROLE_VIEWER})


@router.post("/{vehicle_id}/sharing")
async def sharing_post(request: Request, vehicle_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = VehicleService(db)
    vehicle = service.get_vehicle_for_user(vehicle_id, user, ROLE_OWNER)
    form = FormReader(await request.form())
    action = form.raw.get("action", "add")
    try:
        if action == "add":
            share = service.share_vehicle(vehicle, form.raw.get("email"), form.raw.get("role", ROLE_VIEWER))
            flash(request, f"Vozidlo je nyní sdíleno s uživatelem {share.user.name}.")
        elif action == "role":
            service.update_share_role(vehicle, int(form.raw.get("share_id", 0)), form.raw.get("role"))
            flash(request, "Oprávnění bylo změněno.")
        elif action == "remove":
            service.remove_share(vehicle, int(form.raw.get("share_id", 0)))
            flash(request, "Sdílení bylo zrušeno.")
        elif action == "transfer":
            service.transfer_ownership(vehicle, int(form.raw.get("share_id", 0)))
            flash(request, "Vozidlo bylo předáno novému vlastníkovi. Vám zůstalo právo úprav.")
            return RedirectResponse(f"/vehicles/{vehicle_id}", status_code=303)
    except (ValidationError, ValueError) as e:
        return render(request, "vehicles/sharing.html", status_code=400, vehicle=vehicle,
                      shares=service.get_shares(vehicle), share_roles=SHARE_ROLES,
                      values=form.values, error=str(e))
    return RedirectResponse(f"/vehicles/{vehicle_id}/sharing", status_code=303)


@router.post("/{vehicle_id}/leave")
async def leave_vehicle(request: Request, vehicle_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = VehicleService(db)
    vehicle = service.get_vehicle_for_user(vehicle_id, user, ROLE_VIEWER)
    service.leave_vehicle(vehicle, user)
    flash(request, f"Vozidlo {vehicle.display_name} už s vámi není sdíleno.")
    return RedirectResponse("/vehicles", status_code=303)


# ----------------------------------------------------------------------
# Statistiky
# ----------------------------------------------------------------------

@router.get("/{vehicle_id}/stats")
async def vehicle_stats(request: Request, vehicle_id: int, period: Optional[str] = None,
                        date_from: Optional[str] = None, date_to: Optional[str] = None,
                        user=Depends(get_current_user), db=Depends(get_db)):
    service = VehicleService(db)
    vehicle = service.get_vehicle_for_user(vehicle_id, user)
    stats_service = StatsService(db)

    today = date.today()
    years = sorted({r.refuel_datetime.year for r in vehicle.fuel_records}
                   | {r.service_date.year for r in vehicle.service_records}
                   | {e.expense_date.year for e in vehicle.expenses}
                   | {today.year}, reverse=True)

    period, date_from, date_to = parse_period(period, today, date_from, date_to)

    summary = stats_service.vehicle_summary(vehicle.id, date_from, date_to)
    return render(request, "vehicles/stats.html", summary=summary,
                  breakdown=stats_service.fuel_breakdown(vehicle.id, date_from, date_to), period=period, years=years,
                  date_from=date_from, date_to=date_to, tab="stats",
                  insights=insights(db, [vehicle], date_from, date_to),
                  **vehicle_head(db, vehicle, service.get_role(vehicle, user)))
