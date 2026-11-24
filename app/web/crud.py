"""Společné CRUD routy (přidat / upravit / smazat) pro záznamy navázané na vozidlo."""
from dataclasses import dataclass, field
from typing import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from models.vehicle import ROLE_EDITOR
from services.errors import ValidationError, NotFoundError
from services.vehicle_service import VehicleService
from web.common import editable_vehicles, check_record_access, flash_vehicle_alerts, COMMON_CURRENCIES
from web.deps import get_db, get_current_user, flash, render
from web.forms import FormReader


@dataclass
class CrudConfig:
    prefix: str                      # např. "/services"
    service_cls: type                # služba s metodami get/create/update/delete
    template: str                    # šablona formuláře
    read_form: Callable              # (FormReader) -> dict pro službu
    to_values: Callable              # (record) -> dict hodnot formuláře
    default_values: Callable = lambda vehicle_id: {}
    extra_context: Callable = lambda db, user: {}
    messages: dict = field(default_factory=dict)
    prefill_params: tuple = ()       # pole formuláře, která lze předvyplnit z URL (?category=...)
    track_author: bool = False       # uložit created_by_id (kdo záznam zapsal)
    redirect: Callable = None        # (vehicle) -> URL po uložení / smazání; výchozí detail vozidla


def register_crud(router: APIRouter, cfg: CrudConfig):
    def done_url(vehicle):
        return cfg.redirect(vehicle) if cfg.redirect else f"/vehicles/{vehicle.id}"

    def context(db, user, record=None):
        return {"record": record, "vehicles": editable_vehicles(db, user), "currencies": COMMON_CURRENCIES,
                **cfg.extra_context(db, user)}

    async def add_form(request: Request, vehicle_id: int = None, user=Depends(get_current_user), db=Depends(get_db)):
        ctx = context(db, user)
        if vehicle_id is None and len(ctx["vehicles"]) == 1:
            vehicle_id = ctx["vehicles"][0].id
        values = {"vehicle_id": str(vehicle_id or ""), **cfg.default_values(vehicle_id)}
        for name in cfg.prefill_params:
            if request.query_params.get(name):
                values[name] = request.query_params[name][:100]
        return render(request, cfg.template, values=values, **ctx)

    async def add_post(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
        form = FormReader(await request.form())
        try:
            data = cfg.read_form(form)
            vehicle = VehicleService(db).get_vehicle_for_user(data["vehicle_id"], user, ROLE_EDITOR)
            if cfg.track_author:
                data["created_by_id"] = user.id
            cfg.service_cls(db).create(**data)
        except (ValidationError, NotFoundError) as e:
            db.rollback()
            return render(request, cfg.template, status_code=400, values=form.values, error=str(e),
                          **context(db, user))
        flash(request, cfg.messages.get("created", "Záznam byl uložen."))
        flash_vehicle_alerts(request, db, vehicle)
        return RedirectResponse(done_url(vehicle), status_code=303)

    async def edit_form(request: Request, record_id: int, user=Depends(get_current_user), db=Depends(get_db)):
        record = cfg.service_cls(db).get(record_id)
        check_record_access(db, user, record, ROLE_EDITOR)
        return render(request, cfg.template, values=cfg.to_values(record), **context(db, user, record))

    async def edit_post(request: Request, record_id: int, user=Depends(get_current_user), db=Depends(get_db)):
        service = cfg.service_cls(db)
        record = service.get(record_id)
        check_record_access(db, user, record, ROLE_EDITOR)
        form = FormReader(await request.form())
        try:
            data = cfg.read_form(form)
            vehicle = VehicleService(db).get_vehicle_for_user(data["vehicle_id"], user, ROLE_EDITOR)
            service.update(record, data)
        except (ValidationError, NotFoundError) as e:
            db.rollback()
            return render(request, cfg.template, status_code=400, values=form.values, error=str(e),
                          **context(db, user, record))
        flash(request, cfg.messages.get("updated", "Změny byly uloženy."))
        flash_vehicle_alerts(request, db, vehicle)
        return RedirectResponse(done_url(vehicle), status_code=303)

    async def delete_post(request: Request, record_id: int, user=Depends(get_current_user), db=Depends(get_db)):
        service = cfg.service_cls(db)
        record = service.get(record_id)
        vehicle = check_record_access(db, user, record, ROLE_EDITOR)
        service.delete(record)
        flash(request, cfg.messages.get("deleted", "Záznam byl smazán."))
        return RedirectResponse(done_url(vehicle), status_code=303)

    router.add_api_route(f"{cfg.prefix}/add", add_form, methods=["GET"])
    router.add_api_route(f"{cfg.prefix}/add", add_post, methods=["POST"])
    router.add_api_route(f"{cfg.prefix}/{{record_id}}/edit", edit_form, methods=["GET"])
    router.add_api_route(f"{cfg.prefix}/{{record_id}}/edit", edit_post, methods=["POST"])
    router.add_api_route(f"{cfg.prefix}/{{record_id}}/delete", delete_post, methods=["POST"])
