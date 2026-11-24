"""Pneumatiky: sklad gum / párů / sad, přezutí na vozidla, poškození, životnost."""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from models.tire import (
    DAMAGE_POSITIONS, LEGAL_MIN_TREAD, TIRE_MAX_AGE_YEARS, TIRE_PLACES, TIRE_POSITIONS, TIRE_RIMS, TIRE_SEASONS,
)
from models.vehicle import ROLE_EDITOR
from services.errors import NotFoundError, ValidationError
from services.tire_service import (
    TireDefectService, TireService, TireSwapService, open_mounts, tire_stats,
)
from services.vehicle_service import VehicleService
from web.common import COMMON_CURRENCIES, check_record_access, editable_vehicles, visible_vehicles
from web.deps import get_db, get_current_user, flash, render
from web.forms import FormReader, iso, parse_filter_int, rate_from_record

router = APIRouter()

MOUNT_ROWS = 4
STATUSES = {"active": "Na voze a uskladněné", "mounted": "Na voze", "stored": "Uskladněné",
            "retired": "Vyřazené", "all": "Všechny"}


def _price_form(form, label="Cena"):
    return {
        "price_paid": form.decimal("price_paid", label, min_value=0),
        "currency_code": form.str("currency_code", "Měna") or "CZK",
        "manual_rate": form.decimal("manual_rate", "Kurz", positive=True),
    }


def _price_values(record):
    if record is None or record.price_paid is None:
        return {"price_paid": "", "currency_code": "CZK", "manual_rate": ""}
    return {"price_paid": iso(record.price_paid), "currency_code": record.currency_code,
            "manual_rate": rate_from_record(record)}


def _editable_vehicle(db, user, vehicle_id, required=True):
    if not vehicle_id:
        if required:
            raise ValidationError("Vyberte vozidlo.")
        return None
    return VehicleService(db).get_vehicle_for_user(vehicle_id, user, ROLE_EDITOR)


# ----------------------------------------------------------------------
# Přehled pneumatik
# ----------------------------------------------------------------------

@router.get("/tires")
async def tires_page(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    q = request.query_params
    status = q.get("status") if q.get("status") in STATUSES else "active"
    season = q.get("season") if q.get("season") in TIRE_SEASONS else ""
    vehicle_id = parse_filter_int(q.get("vehicle_id"))
    vehicles = visible_vehicles(db, user)
    tires = TireService(db).list_for_user(user)
    rows = tire_stats(db, tires)
    if status == "active":
        rows = [r for r in rows if r["status"] != "retired"]
    elif status != "all":
        rows = [r for r in rows if r["status"] == status]
    if season:
        rows = [r for r in rows if r["tire"].season == season]
    if vehicle_id:
        rows = [r for r in rows if any(m.vehicle_id == vehicle_id for m in r["tire"].mounts)]
    order = {"mounted": 0, "stored": 1, "retired": 2}
    rows.sort(key=lambda r: (order[r["status"]], r["mount"].vehicle.display_name if r["mount"] else "",
                             r["tire"].season, r["tire"].manufacturer))

    vehicle_ids = [v.id for v in vehicles if vehicle_id in (None, v.id)]
    swap_service = TireSwapService(db)
    swaps = swap_service.for_vehicles(vehicle_ids, limit=50)
    defects = TireDefectService(db).for_tires([r["tire"].id for r in rows])
    mounted = {v.id: open_mounts(db, v.id) for v in vehicles if vehicle_id in (None, v.id)}
    return render(request, "tires/list.html", rows=rows, vehicles=vehicles, swaps=swaps, defects=defects,
                  mounted=mounted, statuses=STATUSES, seasons=TIRE_SEASONS,
                  filters={"status": status, "season": season, "vehicle_id": vehicle_id},
                  can_delete_swap={s.id: swap_service.can_delete(s) for s in swaps},
                  editable_ids=set(VehicleService(db).get_accessible_ids(user, ROLE_EDITOR)),
                  max_age=TIRE_MAX_AGE_YEARS, legal_min=LEGAL_MIN_TREAD)


# ----------------------------------------------------------------------
# Pneumatika (guma / pár / sada)
# ----------------------------------------------------------------------

def _tire_context(db, user, tire=None):
    return {"tire": tire, "seasons": TIRE_SEASONS, "rims": TIRE_RIMS, "currencies": COMMON_CURRENCIES,
            "vehicles": editable_vehicles(db, user)}


def _read_tire(form):
    data = {
        "season": form.str("season", "Typ", required=True),
        "manufacturer": form.str("manufacturer", "Výrobce", required=True, max_len=50),
        "model": form.str("model", "Model", max_len=50),
        "size": form.str("size", "Rozměr", max_len=30),
        "production_year": form.int("production_year", "Rok výroby", min_value=1990,
                                    max_value=date.today().year + 1),
        "dot": form.str("dot", "DOT", max_len=10),
        "quantity": form.int("quantity", "Počet kusů", min_value=1, max_value=8),
        "rim": form.str("rim", "Disky") or "",
        "new_tread_mm": form.decimal("new_tread_mm", "Hloubka dezénu", min_value=0),
        "purchase_date": form.date("purchase_date", "Datum nákupu"),
        "storage_location": form.str("storage_location", "Místo uložení", max_len=100),
        "retired_date": form.date("retired_date", "Vyřazeno"),
        "retired_reason": form.str("retired_reason", "Důvod vyřazení", max_len=200),
        "note": form.str("note", "Poznámka"),
        "expense_vehicle_id": form.int("expense_vehicle_id", "Vozidlo pro výdaj"),
    }
    data["price"] = _price_form(form, "Cena nákupu")
    form.check()
    return data


def _tire_values(t):
    return {
        "season": t.season, "manufacturer": t.manufacturer, "model": t.model or "", "size": t.size or "",
        "production_year": iso(t.production_year), "dot": t.dot or "", "quantity": str(t.quantity),
        "rim": t.rim or "", "new_tread_mm": iso(t.new_tread_mm), "purchase_date": iso(t.purchase_date),
        "storage_location": t.storage_location or "", "retired_date": iso(t.retired_date),
        "retired_reason": t.retired_reason or "", "note": t.note or "",
        "expense_vehicle_id": str(t.expense.vehicle_id) if t.expense else "",
        **_price_values(t),
    }


@router.get("/tires/add")
async def tire_add_form(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    winter = date.today().month in (9, 10, 11, 12, 1, 2)
    values = {"season": "Zimní" if winter else "Letní", "quantity": "2", "rim": "alu", "currency_code": "CZK",
              "purchase_date": date.today().isoformat(),
              "expense_vehicle_id": request.query_params.get("vehicle_id", "")}
    return render(request, "tires/tire_form.html", values=values, **_tire_context(db, user))


async def _save_tire(request, db, user, tire):
    form = FormReader(await request.form())
    try:
        data = _read_tire(form)
        _editable_vehicle(db, user, data["expense_vehicle_id"], required=False)
        service = TireService(db)
        tire = service.update(tire, data) if tire else service.create(user, data)
    except (ValidationError, NotFoundError) as e:
        db.rollback()
        return render(request, "tires/tire_form.html", status_code=400, values=form.values, error=str(e),
                      **_tire_context(db, user, tire))
    flash(request, f"Pneumatika {tire.label} byla uložena.")
    return RedirectResponse("/tires", status_code=303)


@router.post("/tires/add")
async def tire_add(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return await _save_tire(request, db, user, None)


@router.get("/tires/{tire_id}/edit")
async def tire_edit_form(request: Request, tire_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    tire = TireService(db).get_for_user(user, tire_id)
    stats = tire_stats(db, [tire])[0]
    return render(request, "tires/tire_form.html", values=_tire_values(tire), stats=stats,
                  defects=TireDefectService(db).for_tires([tire.id]), **_tire_context(db, user, tire))


@router.post("/tires/{tire_id}/edit")
async def tire_edit(request: Request, tire_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    tire = TireService(db).get_for_user(user, tire_id)
    return await _save_tire(request, db, user, tire)


@router.post("/tires/{tire_id}/delete")
async def tire_delete(request: Request, tire_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = TireService(db)
    tire = service.get_for_user(user, tire_id)
    label = tire.label
    service.delete(tire)
    flash(request, f"Pneumatika {label} byla smazána.")
    return RedirectResponse("/tires", status_code=303)


# ----------------------------------------------------------------------
# Přezutí
# ----------------------------------------------------------------------

def _tire_location(tire):
    mount = tire.open_mount
    if mount:
        return f"na {mount.vehicle.display_name} – {mount.position_label.lower()}"
    return "uskladněno" + (f" – {tire.storage_location}" if tire.storage_location else "")


def _swap_context(db, user, vehicle, swap=None):
    tires = TireService(db).list_for_user(user, include_retired=False)
    return {
        "vehicle": vehicle, "swap": swap, "vehicles": editable_vehicles(db, user),
        "current": open_mounts(db, vehicle.id) if vehicle and swap is None else [],
        "tire_options": [(t, _tire_location(t)) for t in tires],
        "positions": {k: v[0] for k, v in TIRE_POSITIONS.items()}, "places": TIRE_PLACES,
        "currencies": COMMON_CURRENCIES, "mount_rows": range(MOUNT_ROWS),
        "odometer": VehicleService(db).get_current_odometer(vehicle.id) if vehicle else None,
        "can_delete": TireSwapService(db).can_delete(swap) if swap else False,
    }


def _read_swap_base(form):
    data = {
        "swap_date": form.date("swap_date", "Datum", required=True),
        "odometer": form.int("odometer", "Stav tachometru", required=True, min_value=0),
        "place": form.str("place", "Kde") or "home",
        "service_place": form.str("service_place", "Servis", max_len=100),
        "note": form.str("note", "Poznámka"),
        "price": _price_form(form, "Cena přezutí"),
    }
    treads = {}
    for key in form.raw.keys():
        if key.startswith("tread_") and key[6:].isdigit():
            treads[int(key[6:])] = form.decimal(key, "Dezén", min_value=0)
    form.check()
    data["treads"] = {k: v for k, v in treads.items() if v is not None}
    return data


@router.get("/tire-swaps/add")
async def swap_add_form(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    vehicles = editable_vehicles(db, user)
    vehicle_id = parse_filter_int(request.query_params.get("vehicle_id"))
    if vehicle_id is None and len(vehicles) == 1:
        vehicle_id = vehicles[0].id
    vehicle = _editable_vehicle(db, user, vehicle_id) if vehicle_id else None
    values = {"swap_date": date.today().isoformat(), "place": "home", "currency_code": "CZK",
              "mount_tire_0": request.query_params.get("tire_id", ""), "mount_pos_0": "all"}
    return render(request, "tires/swap_form.html", values=values, **_swap_context(db, user, vehicle))


@router.post("/tire-swaps/add")
async def swap_add(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    form = FormReader(await request.form())
    vehicle_id = parse_filter_int(form.raw.get("vehicle_id"))
    if not vehicle_id:
        return RedirectResponse("/tire-swaps/add", status_code=303)
    vehicle = _editable_vehicle(db, user, vehicle_id)
    try:
        data = _read_swap_base(form)
        tire_service = TireService(db)
        new_mounts = []
        for i in range(MOUNT_ROWS):
            tire_id = parse_filter_int(form.raw.get(f"mount_tire_{i}"))
            if tire_id:
                new_mounts.append((tire_service.get_for_user(user, tire_id), form.raw.get(f"mount_pos_{i}") or ""))
        remove_ids = [int(k[7:]) for k in form.raw.keys() if k.startswith("remove_") and k[7:].isdigit()]
        TireSwapService(db).create(vehicle, data["swap_date"], data["odometer"], data["place"],
                                   data["service_place"], data["price"], data["note"],
                                   new_mounts=new_mounts, remove_ids=remove_ids, treads=data["treads"])
    except (ValidationError, NotFoundError) as e:
        db.rollback()
        return render(request, "tires/swap_form.html", status_code=400, values=form.values, error=str(e),
                      **_swap_context(db, user, vehicle))
    flash(request, "Přezutí bylo uloženo.")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


def _swap_values(swap):
    service = swap.service_record
    values = {"vehicle_id": str(swap.vehicle_id), "swap_date": iso(swap.swap_date), "odometer": str(swap.odometer),
              "place": swap.place, "service_place": (service.place or "") if service else "",
              "note": swap.note or "", **_price_values(service)}
    for m in swap.removed:
        values[f"tread_{m.id}"] = iso(m.removed_tread_mm)
    return values


@router.get("/tire-swaps/{swap_id}/edit")
async def swap_edit_form(request: Request, swap_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    swap = TireSwapService(db).get(swap_id)
    vehicle = check_record_access(db, user, swap, ROLE_EDITOR)
    return render(request, "tires/swap_form.html", values=_swap_values(swap), **_swap_context(db, user, vehicle, swap))


@router.post("/tire-swaps/{swap_id}/edit")
async def swap_edit(request: Request, swap_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = TireSwapService(db)
    swap = service.get(swap_id)
    vehicle = check_record_access(db, user, swap, ROLE_EDITOR)
    form = FormReader(await request.form())
    try:
        data = _read_swap_base(form)
        service.update(swap, data["swap_date"], data["odometer"], data["place"], data["service_place"],
                       data["price"], data["note"], treads=data["treads"])
    except ValidationError as e:
        db.rollback()
        return render(request, "tires/swap_form.html", status_code=400, values=form.values, error=str(e),
                      **_swap_context(db, user, vehicle, swap))
    flash(request, "Přezutí bylo upraveno.")
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/tire-swaps/{swap_id}/delete")
async def swap_delete(request: Request, swap_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = TireSwapService(db)
    swap = service.get(swap_id)
    vehicle = check_record_access(db, user, swap, ROLE_EDITOR)
    try:
        service.delete(swap)
        flash(request, "Přezutí bylo smazáno, pneumatiky jsou zpět jako před ním.")
    except ValidationError as e:
        flash(request, str(e), "danger")
    return RedirectResponse(f"/tires?vehicle_id={vehicle.id}", status_code=303)


# ----------------------------------------------------------------------
# Poškození
# ----------------------------------------------------------------------

def _defect_context(db, user, defect=None):
    return {"defect": defect, "tires": TireService(db).list_for_user(user), "vehicles": editable_vehicles(db, user),
            "positions": DAMAGE_POSITIONS, "currencies": COMMON_CURRENCIES}


def _read_defect(form):
    data = {
        "tire_id": form.int("tire_id", "Pneumatika", required=True),
        "vehicle_id": form.int("vehicle_id", "Vozidlo"),
        "defect_date": form.date("defect_date", "Datum", required=True),
        "odometer": form.int("odometer", "Stav tachometru", min_value=0),
        "position": form.str("position", "Pozice", max_len=20),
        "description": form.str("description", "Co se stalo", required=True, max_len=200),
        "price": _price_form(form, "Cena opravy"),
    }
    form.check()
    return data


async def _save_defect(request, db, user, defect):
    form = FormReader(await request.form())
    try:
        data = _read_defect(form)
        tire = TireService(db).get_for_user(user, data["tire_id"])
        vehicle = _editable_vehicle(db, user, data["vehicle_id"], required=False)
        TireDefectService(db).save(defect, tire, data, data["price"], vehicle.id if vehicle else None)
    except (ValidationError, NotFoundError) as e:
        db.rollback()
        return render(request, "tires/defect_form.html", status_code=400, values=form.values, error=str(e),
                      **_defect_context(db, user, defect))
    flash(request, "Poškození bylo uloženo.")
    return RedirectResponse("/tires", status_code=303)


def _owned_defect(db, user, defect_id):
    defect = TireDefectService(db).get(defect_id)
    if defect is None or defect.tire.owner_id != user.id:
        raise NotFoundError("Záznam nenalezen.")
    return defect


@router.get("/tire-defects/add")
async def defect_add_form(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    values = {"tire_id": request.query_params.get("tire_id", ""), "defect_date": date.today().isoformat(),
              "currency_code": "CZK"}
    return render(request, "tires/defect_form.html", values=values, **_defect_context(db, user))


@router.post("/tire-defects/add")
async def defect_add(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return await _save_defect(request, db, user, None)


@router.get("/tire-defects/{defect_id}/edit")
async def defect_edit_form(request: Request, defect_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    d = _owned_defect(db, user, defect_id)
    values = {"tire_id": str(d.tire_id), "vehicle_id": str(d.vehicle_id or ""), "defect_date": iso(d.defect_date),
              "odometer": iso(d.odometer), "position": d.position or "", "description": d.description,
              **_price_values(d.expense)}
    return render(request, "tires/defect_form.html", values=values, **_defect_context(db, user, d))


@router.post("/tire-defects/{defect_id}/edit")
async def defect_edit(request: Request, defect_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    return await _save_defect(request, db, user, _owned_defect(db, user, defect_id))


@router.post("/tire-defects/{defect_id}/delete")
async def defect_delete(request: Request, defect_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    TireDefectService(db).delete(_owned_defect(db, user, defect_id))
    flash(request, "Poškození bylo smazáno.")
    return RedirectResponse("/tires", status_code=303)
