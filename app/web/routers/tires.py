"""Pneumatiky: přehled sad a jejich životnosti, přezutí, poškození."""
from datetime import date

from fastapi import APIRouter, Depends, Request

from models.tire import LEGAL_MIN_TREAD, TIRE_MAX_AGE_YEARS, TIRE_PLACES, TIRE_POSITIONS, TIRE_RIMS, TIRE_SEASONS
from models.vehicle import ROLE_EDITOR
from services.errors import ValidationError
from services.tire_service import TireChangeService, TireDamageService, TireSetService, tire_overview
from services.vehicle_service import VehicleService
from web.common import editable_vehicles, visible_vehicles
from web.crud import CrudConfig, register_crud
from web.deps import get_db, get_current_user, render
from web.forms import iso, parse_filter_int, rate_from_record

router = APIRouter()


def _tires_url(vehicle):
    return f"/tires?vehicle_id={vehicle.id}"


def _price_values(record):
    """Cena z navázaného výdaje / servisu pro formulář."""
    if record is None or record.price_paid is None:
        return {"price_paid": "", "currency_code": "CZK", "manual_rate": ""}
    return {"price_paid": iso(record.price_paid), "currency_code": record.currency_code,
            "manual_rate": rate_from_record(record)}


def _price_form(form):
    return {
        "price_paid": form.decimal("price_paid", "Cena", min_value=0),
        "currency_code": form.str("currency_code", "Měna") or "CZK",
        "manual_rate": form.decimal("manual_rate", "Kurz", positive=True),
    }


def _sets_context(db, user):
    ids = [v.id for v in editable_vehicles(db, user)]
    return {"tire_sets": TireSetService(db).list_for_vehicles(ids, include_retired=False)}


# ----------------------------------------------------------------------
# Přehled
# ----------------------------------------------------------------------

@router.get("/tires")
async def tires_page(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    vehicles = visible_vehicles(db, user)
    vehicle_id = parse_filter_int(request.query_params.get("vehicle_id"))
    selected = [v for v in vehicles if vehicle_id in (None, v.id)]
    vehicle_service = VehicleService(db)
    sections = []
    for vehicle in selected:
        overview = tire_overview(db, vehicle, vehicle_service.get_current_odometer(vehicle.id))
        changes = list(reversed(TireChangeService(db).for_vehicle(vehicle.id)))
        damages = TireDamageService(db).search([vehicle.id])
        if overview or changes or vehicle_id:
            sections.append({"vehicle": vehicle, "overview": overview, "changes": changes, "damages": damages})
    return render(request, "tires/list.html", vehicles=vehicles, filters={"vehicle_id": vehicle_id},
                  sections=sections, max_age=TIRE_MAX_AGE_YEARS, legal_min=LEGAL_MIN_TREAD,
                  editable_ids=set(vehicle_service.get_accessible_ids(user, ROLE_EDITOR)))


# ----------------------------------------------------------------------
# Sady
# ----------------------------------------------------------------------

def _read_set(form):
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "season": form.str("season", "Typ", required=True),
        "manufacturer": form.str("manufacturer", "Výrobce", required=True, max_len=50),
        "model": form.str("model", "Model", max_len=50),
        "size": form.str("size", "Rozměr", max_len=30),
        "production_year": form.int("production_year", "Rok výroby", min_value=1990,
                                    max_value=date.today().year + 1),
        "dot": form.str("dot", "DOT", max_len=10),
        "quantity": form.int("quantity", "Počet kusů", min_value=1, max_value=20),
        "rim": form.str("rim", "Disky") or "",
        "new_tread_mm": form.decimal("new_tread_mm", "Hloubka dezénu", min_value=0),
        "purchase_date": form.date("purchase_date", "Datum nákupu"),
        "storage_location": form.str("storage_location", "Místo uložení", max_len=100),
        "retired_date": form.date("retired_date", "Vyřazeno"),
        "retired_reason": form.str("retired_reason", "Důvod vyřazení", max_len=200),
        "note": form.str("note", "Poznámka"),
        **_price_form(form),
    }
    form.check()
    return data


def _set_values(t):
    return {
        "vehicle_id": str(t.vehicle_id), "season": t.season, "manufacturer": t.manufacturer,
        "model": t.model or "", "size": t.size or "", "production_year": iso(t.production_year),
        "dot": t.dot or "", "quantity": str(t.quantity), "rim": t.rim or "", "new_tread_mm": iso(t.new_tread_mm),
        "purchase_date": iso(t.purchase_date), "storage_location": t.storage_location or "",
        "retired_date": iso(t.retired_date), "retired_reason": t.retired_reason or "", "note": t.note or "",
        **_price_values(t.expense),
    }


def _set_defaults(vehicle_id):
    winter = date.today().month in (9, 10, 11, 12, 1, 2)
    return {"season": "Zimní" if winter else "Letní", "quantity": "4", "rim": "alu", "currency_code": "CZK",
            "purchase_date": date.today().isoformat()}


register_crud(router, CrudConfig(
    prefix="/tires",
    service_cls=TireSetService,
    template="tires/set_form.html",
    read_form=_read_set,
    to_values=_set_values,
    default_values=_set_defaults,
    extra_context=lambda db, user: {"seasons": TIRE_SEASONS, "rims": TIRE_RIMS},
    messages={"created": "Sada pneumatik byla uložena.", "updated": "Sada pneumatik byla upravena.",
              "deleted": "Sada pneumatik byla smazána."},
    redirect=_tires_url,
))


# ----------------------------------------------------------------------
# Přezutí
# ----------------------------------------------------------------------

def _read_change(form):
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "change_date": form.date("change_date", "Datum", required=True),
        "odometer": form.int("odometer", "Stav tachometru", required=True, min_value=0),
        "tire_set_id": form.int("tire_set_id", "Nasazená sada", required=True),
        "place": form.str("place", "Kde") or "home",
        "service_place": form.str("service_place", "Servis", max_len=100),
        "removed_tread_mm": form.decimal("removed_tread_mm", "Dezén sundané sady", min_value=0),
        "note": form.str("note", "Poznámka"),
        **_price_form(form),
    }
    form.check()
    if data["change_date"] > date.today():
        raise ValidationError("Datum přezutí nemůže být v budoucnosti.")
    return data


def _change_values(c):
    service = c.service_record
    return {
        "vehicle_id": str(c.vehicle_id), "change_date": iso(c.change_date), "odometer": str(c.odometer),
        "tire_set_id": str(c.tire_set_id), "place": c.place, "removed_tread_mm": iso(c.removed_tread_mm),
        "service_place": (service.place or "") if service else "", "note": c.note or "",
        **_price_values(service),
    }


register_crud(router, CrudConfig(
    prefix="/tire-changes",
    service_cls=TireChangeService,
    template="tires/change_form.html",
    read_form=_read_change,
    to_values=_change_values,
    default_values=lambda vid: {"change_date": date.today().isoformat(), "place": "home", "currency_code": "CZK"},
    extra_context=lambda db, user: {**_sets_context(db, user), "places": TIRE_PLACES},
    messages={"created": "Přezutí bylo uloženo.", "updated": "Přezutí bylo upraveno.",
              "deleted": "Přezutí bylo smazáno."},
    prefill_params=("tire_set_id",),
    redirect=_tires_url,
))


# ----------------------------------------------------------------------
# Poškození
# ----------------------------------------------------------------------

def _read_damage(form):
    data = {
        "vehicle_id": form.int("vehicle_id", "Vozidlo", required=True),
        "tire_set_id": form.int("tire_set_id", "Sada", required=True),
        "damage_date": form.date("damage_date", "Datum", required=True),
        "odometer": form.int("odometer", "Stav tachometru", min_value=0),
        "position": form.str("position", "Pozice", max_len=20),
        "description": form.str("description", "Popis", required=True, max_len=200),
        **_price_form(form),
    }
    form.check()
    return data


def _damage_values(d):
    return {
        "vehicle_id": str(d.vehicle_id), "tire_set_id": str(d.tire_set_id), "damage_date": iso(d.damage_date),
        "odometer": iso(d.odometer), "position": d.position or "", "description": d.description,
        **_price_values(d.expense),
    }


register_crud(router, CrudConfig(
    prefix="/tire-damages",
    service_cls=TireDamageService,
    template="tires/damage_form.html",
    read_form=_read_damage,
    to_values=_damage_values,
    default_values=lambda vid: {"damage_date": date.today().isoformat(), "currency_code": "CZK"},
    extra_context=lambda db, user: {**_sets_context(db, user), "positions": TIRE_POSITIONS},
    messages={"created": "Poškození bylo zapsáno.", "updated": "Poškození bylo upraveno.",
              "deleted": "Poškození bylo smazáno."},
    prefill_params=("tire_set_id",),
    redirect=_tires_url,
))
