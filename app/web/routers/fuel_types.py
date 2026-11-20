"""Správa seznamu paliv uživatele (nabídka ve formuláři tankování)."""
from collections import Counter

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func

from models import FuelRecord
from models.fuel_record import FUEL_CATEGORIES, fuel_unit
from services.errors import ValidationError
from services.fuel_type_service import FuelTypeService
from services.vehicle_service import VehicleService
from web.deps import get_db, get_current_user, flash, render
from web.forms import FormReader

router = APIRouter(prefix="/fuel-types")


def _page(request, db, user, status_code=200, error=None, values=None):
    items = FuelTypeService(db).list_for_user(user)
    ids = VehicleService(db).get_accessible_ids(user)
    usage = Counter()
    if ids:
        rows = (db.query(func.lower(FuelRecord.fuel_type), func.count(FuelRecord.id))
                .filter(FuelRecord.vehicle_id.in_(ids)).group_by(func.lower(FuelRecord.fuel_type)).all())
        usage.update({name: count for name, count in rows})
    return render(request, "fuel_types/list.html", status_code=status_code, error=error,
                  items=items, usage={t.id: usage.get(t.name.lower(), 0) for t in items},
                  categories=[(c, fuel_unit(c)) for c in FUEL_CATEGORIES], values=values or {})


@router.get("")
async def list_fuel_types(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    return _page(request, db, user)


@router.post("/add")
async def add_fuel_type(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    form = FormReader(await request.form())
    try:
        item = FuelTypeService(db).create(user, form.raw.get("name"), form.raw.get("category"))
    except ValidationError as e:
        db.rollback()
        return _page(request, db, user, 400, str(e), values=form.values)
    flash(request, f"Palivo „{item.name}“ bylo přidáno.")
    return RedirectResponse("/fuel-types", status_code=303)


@router.post("/{fuel_type_id}/edit")
async def edit_fuel_type(request: Request, fuel_type_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = FuelTypeService(db)
    item = service.get(user, fuel_type_id)
    form = FormReader(await request.form())
    try:
        changed = service.update(user, item, form.raw.get("name"), form.raw.get("category"))
    except ValidationError as e:
        db.rollback()
        return _page(request, db, user, 400, str(e))
    message = f"Palivo „{item.name}“ bylo uloženo."
    if changed:
        message += f" Upraveno tankování: {changed}, spotřeba přepočítána."
    flash(request, message)
    return RedirectResponse("/fuel-types", status_code=303)


@router.post("/{fuel_type_id}/delete")
async def delete_fuel_type(request: Request, fuel_type_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    service = FuelTypeService(db)
    item = service.get(user, fuel_type_id)
    name = item.name
    service.delete(user, item)
    flash(request, f"Palivo „{name}“ bylo odebráno z nabídky.")
    return RedirectResponse("/fuel-types", status_code=303)
