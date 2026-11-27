"""Pneumatiky: sklad gum / párů / sad, přezutí na vozidla, poškození, životnost."""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from models.tire import (
    CAR_WHEELS, DAMAGE_POSITIONS, LEGAL_MIN_TREAD, LEGAL_MIN_TREAD_MOTO, TIRE_RETIRED_REASONS, TIRE_MAX_AGE_YEARS, TIRE_PLACES, TIRE_POSITIONS, TIRE_RIMS, TIRE_SEASONS, TIRE_KINDS,
    positions_for,
)
from models import TireRetirement
from models.vehicle import ROLE_EDITOR
from services.errors import NotFoundError, ValidationError
from services.tire_service import (
    TireDefectService, TireRetirementService, TireService, TireSwapService, TireTreadCheckService, last_readings,
    mounted_pieces, mounts_on, open_mounts, tires_on_vehicle,
    tire_stats, wheel_layout,
)
from services.vehicle_service import VehicleService
from web import record_views
from web.common import COMMON_CURRENCIES, check_record_access, editable_vehicles, render_record, visible_vehicles
from web.deps import get_db, get_current_user, flash, render
from web.forms import FormReader, iso, parse_filter_int, rate_from_record

router = APIRouter()

MOUNT_ROWS = 5  # 4 kola + rezerva
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
    kind = q.get("kind") if q.get("kind") in TIRE_KINDS else ""
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
    if kind:
        rows = [r for r in rows if (r["tire"].kind or "car") == kind]
    if vehicle_id:
        rows = [r for r in rows if any(m.vehicle_id == vehicle_id for m in r["tire"].mounts)]
    order = {"mounted": 0, "stored": 1, "retired": 2}
    rows.sort(key=lambda r: (order[r["status"]], r["mount"].vehicle.short_name if r["mount"] else "",
                             r["tire"].season, r["tire"].manufacturer))

    shown = [v for v in vehicles if vehicle_id in (None, v.id) and kind in ("", v.kind or "car")]
    vehicle_ids = [v.id for v in shown]
    swap_service = TireSwapService(db)
    swaps = swap_service.for_vehicles(vehicle_ids, limit=50)
    defects = TireDefectService(db).for_tires([r["tire"].id for r in rows])
    mounted = {v.id: open_mounts(db, v.id) for v in shown}
    on_vehicles = [(v, tires_on_vehicle(mounted[v.id])) for v in shown if mounted[v.id]]
    checks = TireTreadCheckService(db).for_vehicles(vehicle_ids, limit=30)
    return render(request, "tires/list.html", rows=rows, vehicles=vehicles, swaps=swaps, defects=defects,
                  checks=checks,
                  on_vehicles=on_vehicles, statuses=STATUSES, seasons=TIRE_SEASONS, kinds=TIRE_KINDS,
                  filters={"status": status, "season": season, "kind": kind, "vehicle_id": vehicle_id},
                  can_delete_swap={s.id: swap_service.can_delete(s) for s in swaps},
                  editable_ids=set(VehicleService(db).get_accessible_ids(user, ROLE_EDITOR)),
                  max_age=TIRE_MAX_AGE_YEARS, legal_min=LEGAL_MIN_TREAD)


# ----------------------------------------------------------------------
# Pneumatika (guma / pár / sada)
# ----------------------------------------------------------------------

def _tire_context(db, user, tire=None):
    used = [t.retired_reason for t in TireService(db).list_for_user(user) if t.retired_reason]
    return {"tire": tire, "seasons": TIRE_SEASONS, "kinds": TIRE_KINDS, "rims": TIRE_RIMS, "currencies": COMMON_CURRENCIES,
            "vehicles": editable_vehicles(db, user), "legal_min": LEGAL_MIN_TREAD,
            "legal_min_moto": LEGAL_MIN_TREAD_MOTO,
            "retired_reasons": list(dict.fromkeys(TIRE_RETIRED_REASONS + sorted(used)))}


def _read_tire(form):
    data = {
        "season": form.str("season", "Typ", required=True),
        "kind": form.str("kind", "Pro vozidlo") or "car",
        "manufacturer": form.str("manufacturer", "Výrobce", required=True, max_len=50),
        "model": form.str("model", "Model", max_len=50),
        "size": form.str("size", "Rozměr", max_len=30),
        "production_year": form.int("production_year", "Rok výroby", min_value=1990,
                                    max_value=date.today().year + 1),
        "dot": form.str("dot", "DOT", max_len=10),
        "quantity": form.int("quantity", "Počet kusů", min_value=1, max_value=8),
        "rim": form.str("rim", "Disky") or "",
        "new_tread_mm": form.decimal("new_tread_mm", "Hloubka dezénu", min_value=0),
        "min_tread_mm": form.decimal("min_tread_mm", "Minimální dezén", positive=True),
        "purchase_date": form.date("purchase_date", "Datum nákupu"),
        "storage_location": form.str("storage_location", "Místo uložení", max_len=100),
        "note": form.str("note", "Poznámka"),
        "expense_vehicle_id": form.int("expense_vehicle_id", "Vozidlo pro výdaj"),
    }
    data["price"] = _price_form(form, "Cena nákupu")
    form.check()
    return data


def _tire_values(t):
    return {
        "season": t.season, "kind": t.kind or "car", "manufacturer": t.manufacturer, "model": t.model or "", "size": t.size or "",
        "production_year": iso(t.production_year), "dot": t.dot or "", "quantity": str(t.quantity),
        "rim": t.rim or "", "new_tread_mm": iso(t.new_tread_mm),
        "min_tread_mm": iso(t.min_tread_mm), "purchase_date": iso(t.purchase_date),
        "storage_location": t.storage_location or "", "note": t.note or "",
        "expense_vehicle_id": str(t.expense.vehicle_id) if t.expense else "",
        **_price_values(t),
    }


@router.get("/tires/add")
async def tire_add_form(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    winter = date.today().month in (9, 10, 11, 12, 1, 2)
    vehicles = editable_vehicles(db, user)
    chosen = next((v for v in vehicles if str(v.id) == request.query_params.get("vehicle_id")), None)
    kinds = {v.kind or "car" for v in vehicles}
    kind = (chosen.kind or "car") if chosen else (kinds.pop() if len(kinds) == 1 else "car")
    values = {"season": "Zimní" if winter else "Letní", "kind": kind, "quantity": "1" if kind == "moto" else "2",
              "rim": "alu", "currency_code": "CZK",
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
    flash(request, f"Pneumatika {tire.text_label} byla uložena.")
    return RedirectResponse(f"/tires/{tire.id}", status_code=303)


@router.post("/tires/add")
async def tire_add(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return await _save_tire(request, db, user, None)


def _retire_context(db, tire):
    """Formulář vyřazení ve správě pneumatiky: nasazená kola k výběru, kusy ve skladu, tachometr."""
    wheels, vehicle = [], None
    for m in tire.open_mounts:
        vehicle = m.vehicle
        if m.kind == "moto":
            wheels += [(key, short, label) for key, short, label, keys in
                       (("fl", "P", "přední kolo", {"fl", "fr"}), ("rl", "Z", "zadní kolo", {"rl", "rr"}))
                       if m.slots & keys]
        else:
            wheels += [(key, short, label) for key, short, label in CAR_WHEELS if key in m.slots]
    order = [w[0] for w in CAR_WHEELS]
    wheels.sort(key=lambda w: order.index(w[0]))
    return {"wheels": wheels, "vehicle": vehicle,
            "in_stock": max(tire.active_quantity - mounted_pieces(tire), 0),
            "odometer": VehicleService(db).get_current_odometer(vehicle.id) if vehicle else None}  # noqa: E501


@router.get("/tires/{tire_id}")
async def tire_detail(request: Request, tire_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    """Detail pneumatiky: stav, životnost, údaje, historie nasazení, měření dezénu a poškození."""
    tire = TireService(db).get_for_user(user, tire_id)
    checks = sorted({r.check for r in tire.tread_readings}, key=lambda c: (c.check_date, c.id), reverse=True)
    used = [t.retired_reason for t in TireService(db).list_for_user(user) if t.retired_reason]
    return render(request, "tires/detail.html", tire=tire, stats=tire_stats(db, [tire])[0],
                  checks=[(c, [r for r in c.readings if r.tire_id == tire.id]) for c in checks],
                  defects=TireDefectService(db).for_tires([tire.id]),
                  editable_ids=set(VehicleService(db).get_accessible_ids(user, ROLE_EDITOR)),
                  retire=_retire_context(db, tire),
                  retired_reasons=list(dict.fromkeys(TIRE_RETIRED_REASONS + sorted(used))))


@router.post("/tires/{tire_id}/retire")
async def tire_retire(request: Request, tire_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    """Vyřazení celé pneumatiky nebo jen některých kol (správa pneumatiky)."""
    tire = TireService(db).get_for_user(user, tire_id)
    form = FormReader(await request.form())
    slots = [key[6:] for key, value in form.raw.items() if key.startswith("wheel_") and value]
    try:
        retire_date = form.date("retire_date", "Datum vyřazení", required=True)
        reason = form.str("reason", "Důvod", max_len=200)
        odometer = form.int("odometer", "Tachometr", min_value=0) if slots else None
        stored = form.int("stored", "Kusů ze skladu", min_value=0, max_value=8)
        form.check()
        retirement = TireRetirementService(db).retire(tire, retire_date, reason, slots, stored or 0, odometer)
    except ValidationError as e:
        db.rollback()
        flash(request, f"Vyřazení se neuložilo: {e}", "danger")
        return RedirectResponse(f"/tires/{tire.id}#retire", status_code=303)
    what = retirement.wheels_label or retirement.quantity_label
    flash(request, f"Pneumatika {tire.text_label} je vyřazená." if tire.retired_date
          else f"Vyřazeno: {tire.text_label} – {what}. Zbývá {tire.active_quantity} ks.")
    return RedirectResponse(f"/tires/{tire.id}", status_code=303)


@router.post("/tire-retirements/{retirement_id}/delete")
async def retirement_cancel(request: Request, retirement_id: int, user=Depends(get_current_user),
                            db=Depends(get_db)):
    retirement = db.get(TireRetirement, retirement_id)
    if retirement is None:
        raise NotFoundError("Vyřazení nenalezeno.")
    tire = TireService(db).get_for_user(user, retirement.tire_id)
    try:
        TireRetirementService(db).cancel(retirement)
        flash(request, "Vyřazení bylo zrušeno" + (" – kola jsou zpět na vozidle." if retirement.swap_id else "."))
    except ValidationError as e:
        db.rollback()
        flash(request, f"Vyřazení nejde zrušit: {e}", "danger")
    return RedirectResponse(f"/tires/{tire.id}", status_code=303)


@router.get("/tires/{tire_id}/edit")
async def tire_edit_form(request: Request, tire_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    tire = TireService(db).get_for_user(user, tire_id)
    return render(request, "tires/tire_form.html", values=_tire_values(tire), **_tire_context(db, user, tire))


@router.post("/tires/{tire_id}/edit")
async def tire_edit(request: Request, tire_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    tire = TireService(db).get_for_user(user, tire_id)
    return await _save_tire(request, db, user, tire)


@router.post("/tires/{tire_id}/delete")
async def tire_delete(request: Request, tire_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = TireService(db)
    tire = service.get_for_user(user, tire_id)
    label = tire.text_label
    service.delete(tire)
    flash(request, f"Pneumatika {label} byla smazána.")
    return RedirectResponse("/tires", status_code=303)


# ----------------------------------------------------------------------
# Přezutí
# ----------------------------------------------------------------------

def _tire_location(tire):
    mount = tire.open_mount
    if mount:
        return f"na {mount.vehicle.short_name} – {mount.position_label.lower()}"
    return "uskladněno" + (f" – {tire.storage_location}" if tire.storage_location else "")


def _diagram(vehicle, current, tires):
    """Data pro nákres vozidla při přezutí (JSON pro app.js)."""
    return {
        "kind": vehicle.kind or "car",
        "slots": {k: sorted(v[1]) for k, v in TIRE_POSITIONS.items()},
        "positions": positions_for(vehicle.kind),
        "current": [{"id": m.id, "tire": m.tire_id, "label": m.tire.text_label, "season": m.tire.season,
                     "position": m.position, "position_label": m.position_label,
                     "wheels": [list(w) for w in m.wheels]} for m in current],
        "tires": {str(t.id): {"label": t.text_label, "season": t.season, "full": t.full_label} for t in tires},
    }


def _swap_context(db, user, vehicle, swap=None):
    tires = TireService(db).list_for_user(user, include_retired=False)
    if vehicle:
        tires = [t for t in tires if (t.kind or "car") == (vehicle.kind or "car")]
    current = open_mounts(db, vehicle.id) if vehicle and swap is None else []
    return {
        "vehicle": vehicle, "swap": swap, "vehicles": editable_vehicles(db, user),
        "current": current,
        "diagram": _diagram(vehicle, current, tires) if vehicle and swap is None else None,
        "tire_options": [(t, _tire_location(t)) for t in tires],
        "positions": positions_for(vehicle.kind if vehicle else None), "places": TIRE_PLACES,
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
    # tread_<id nasazení> (jedna hodnota) nebo tread_<id nasazení>_<kolo> (po kolech)
    treads = {}
    for key in list(form.raw.keys()):
        mount_id, _, wheel = key[6:].partition("_")
        if key.startswith("tread_") and mount_id.isdigit():
            treads.setdefault(int(mount_id), {})[wheel] = form.decimal(key, "Dezén", min_value=0)
    form.check()
    data["treads"] = treads
    return data


@router.get("/tire-swaps/add")
async def swap_add_form(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    vehicles = editable_vehicles(db, user)
    vehicle_id = parse_filter_int(request.query_params.get("vehicle_id"))
    if vehicle_id is None and len(vehicles) == 1:
        vehicle_id = vehicles[0].id
    vehicle = _editable_vehicle(db, user, vehicle_id) if vehicle_id else None
    values = {"swap_date": date.today().isoformat(), "place": "home", "currency_code": "CZK"}
    if request.query_params.get("tire_id"):
        values.update(mount_tire_0=request.query_params.get("tire_id"), mount_pos_0="all")
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
        per_wheel = m.tread_map
        if per_wheel:
            for wheel, mm in per_wheel.items():
                values[f"tread_{m.id}_{wheel}"] = mm
        elif m.removed_tread_mm is not None:
            for wheel in m.wheels:  # dříve zapsaná jedna hodnota pro všechna kola
                values[f"tread_{m.id}_{wheel[0]}"] = iso(m.removed_tread_mm)
    return values


@router.get("/tire-swaps/{swap_id:int}")
async def swap_detail(request: Request, swap_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = TireSwapService(db)
    swap = service.get(swap_id)
    check_record_access(db, user, swap)
    return render_record(request, db, user, swap, record_views.tire_swap(swap, service.can_delete(swap)))


def _retirement_swap(request, swap):
    """Vyřazení kol se neupravuje jako přezutí - jen zrušit ve správě pneumatiky."""
    if swap is not None and swap.is_retirement:
        flash(request, "Vyřazení kol se upravuje zrušením a novým vyřazením ve správě pneumatiky.", "warning")
        tire_id = swap.retirements[0].tire_id if swap.retirements else None
        return RedirectResponse(f"/tires/{tire_id}" if tire_id else f"/tire-swaps/{swap.id}", status_code=303)
    return None


@router.get("/tire-swaps/{swap_id}/edit")
async def swap_edit_form(request: Request, swap_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    swap = TireSwapService(db).get(swap_id)
    vehicle = check_record_access(db, user, swap, ROLE_EDITOR)
    if redirect := _retirement_swap(request, swap):
        return redirect
    return render(request, "tires/swap_form.html", values=_swap_values(swap), **_swap_context(db, user, vehicle, swap))


@router.post("/tire-swaps/{swap_id}/edit")
async def swap_edit(request: Request, swap_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = TireSwapService(db)
    swap = service.get(swap_id)
    vehicle = check_record_access(db, user, swap, ROLE_EDITOR)
    if redirect := _retirement_swap(request, swap):
        return redirect
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


@router.get("/tire-defects/{defect_id:int}")
async def defect_detail(request: Request, defect_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    d = _owned_defect(db, user, defect_id)
    return render(request, "record_detail.html", view=record_views.tire_defect(d), can_edit=True)


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


# ----------------------------------------------------------------------
# Kontrola dezénu (průběžné měření po kolech)
# ----------------------------------------------------------------------

def _check_context(db, user, vehicle, check=None, check_date=None):
    context = {"vehicle": vehicle, "check": check, "vehicles": editable_vehicles(db, user), "wheels": [],
               "last": {}, "odometer": None}
    if vehicle is None:
        return context
    day = check_date or (check.check_date if check else date.today())
    mounts = mounts_on(db, vehicle.id, day)
    if check is not None:
        known = {m.id for m in mounts}
        mounts += [r.mount for r in check.readings if r.mount is not None and r.mount.id not in known]
    context.update(
        wheels=wheel_layout(vehicle, mounts),
        last=last_readings(db, [m.id for m in mounts], before_check_id=check.id if check else None),
        odometer=VehicleService(db).get_current_odometer(vehicle.id),
    )
    return context


def _read_check(form):
    data = {
        "check_date": form.date("check_date", "Datum", required=True),
        "odometer": form.int("odometer", "Stav tachometru", required=True, min_value=0),
        "note": form.str("note", "Poznámka"),
    }
    values = {}
    for key in list(form.raw.keys()):
        mount_id, _, wheel = key[6:].partition("_")
        if key.startswith("tread_") and mount_id.isdigit() and wheel:
            values[(int(mount_id), wheel)] = form.decimal(key, "Dezén", min_value=0)
    form.check()
    data["values"] = values
    return data


async def _save_check(request, db, user, vehicle, check):
    form = FormReader(await request.form())
    try:
        data = _read_check(form)
        check = TireTreadCheckService(db).save(check, vehicle, data["check_date"], data["odometer"], data["note"],
                                               data["values"], user)
    except (ValidationError, NotFoundError) as e:
        db.rollback()
        return render(request, "tires/check_form.html", status_code=400, values=form.values, error=str(e),
                      **_check_context(db, user, vehicle, check, _safe_date(form.raw.get("check_date"))))
    flash(request, "Kontrola dezénu byla uložena.")
    return RedirectResponse(f"/tires?vehicle_id={vehicle.id}", status_code=303)


def _safe_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@router.get("/tire-checks/add")
async def check_add_form(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    vehicles = editable_vehicles(db, user)
    vehicle_id = parse_filter_int(request.query_params.get("vehicle_id"))
    if vehicle_id is None and len(vehicles) == 1:
        vehicle_id = vehicles[0].id
    vehicle = _editable_vehicle(db, user, vehicle_id) if vehicle_id else None
    return render(request, "tires/check_form.html", values={"check_date": date.today().isoformat()},
                  **_check_context(db, user, vehicle))


@router.post("/tire-checks/add")
async def check_add(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    form = await request.form()
    vehicle_id = parse_filter_int(form.get("vehicle_id"))
    if not vehicle_id:
        return RedirectResponse("/tire-checks/add", status_code=303)
    return await _save_check(request, db, user, _editable_vehicle(db, user, vehicle_id), None)


@router.get("/tire-checks/{check_id:int}")
async def check_detail(request: Request, check_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    check = TireTreadCheckService(db).get(check_id)
    check_record_access(db, user, check)
    return render_record(request, db, user, check, record_views.tire_check(check))


@router.get("/tire-checks/{check_id}/edit")
async def check_edit_form(request: Request, check_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    check = TireTreadCheckService(db).get(check_id)
    vehicle = check_record_access(db, user, check, ROLE_EDITOR)
    values = {"vehicle_id": str(vehicle.id), "check_date": iso(check.check_date), "odometer": str(check.odometer),
              "note": check.note or ""}
    for r in check.readings:
        if r.mount_id:
            values[f"tread_{r.mount_id}_{r.wheel}"] = iso(r.tread_mm)
    return render(request, "tires/check_form.html", values=values, **_check_context(db, user, vehicle, check))


@router.post("/tire-checks/{check_id}/edit")
async def check_edit(request: Request, check_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    check = TireTreadCheckService(db).get(check_id)
    vehicle = check_record_access(db, user, check, ROLE_EDITOR)
    return await _save_check(request, db, user, vehicle, check)


@router.post("/tire-checks/{check_id}/delete")
async def check_delete(request: Request, check_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = TireTreadCheckService(db)
    check = service.get(check_id)
    vehicle = check_record_access(db, user, check, ROLE_EDITOR)
    service.delete(check)
    flash(request, "Kontrola dezénu byla smazána.")
    return RedirectResponse(f"/tires?vehicle_id={vehicle.id}", status_code=303)
