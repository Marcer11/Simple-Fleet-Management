"""Místa: servisy, čerpací stanice a místa výdajů - kdy jsem tam byl, s jakým vozidlem a kolik utratil."""
from fastapi import APIRouter, Depends, Request

from models.vehicle import ROLE_EDITOR
from services import places
from services.errors import NotFoundError
from services.fuel_record_service import FuelRecordService
from services.stations import station_overview
from services.vehicle_service import VehicleService
from web.common import visible_vehicles
from web.deps import get_db, get_current_user, render
from web.forms import iso, parse_filter_date, parse_filter_int

router = APIRouter(prefix="/places")


def _filters(request, db, user):
    """Filtr vozidla a období; bez zadaného období celá historie."""
    q = request.query_params
    vehicles = visible_vehicles(db, user)
    vehicle_id = parse_filter_int(q.get("vehicle_id"))
    ids = [v.id for v in vehicles if vehicle_id in (None, v.id)]
    date_from, date_to = parse_filter_date(q.get("date_from")), parse_filter_date(q.get("date_to"))
    if q.get("all") or not (date_from or date_to):
        date_from = date_to = None
    filters = {"vehicle_id": vehicle_id, "date_from": iso(date_from), "date_to": iso(date_to),
               "all": "" if (date_from or date_to) else "1"}
    return vehicles, ids, date_from, date_to, filters


@router.get("")
async def place_list(request: Request, kind: str = "service", user=Depends(get_current_user), db=Depends(get_db)):
    kind = kind if kind in places.KINDS else "service"
    vehicles, ids, date_from, date_to, filters = _filters(request, db, user)
    items = places.overview(db, kind, ids, date_from, date_to)
    brands = None
    if kind == "station":
        brands = station_overview(FuelRecordService(db).search(ids, date_from, date_to))
    counts = {k: (len(items) if k == kind else len(places.overview(db, k, ids, date_from, date_to)))
              for k in places.KINDS}
    return render(request, "places/list.html", kind=kind, kinds=places.KINDS, items=items, brands=brands,
                  counts=counts, vehicles=vehicles, filters=filters,
                  total_cost=sum((p["cost"] for p in items), 0), total_count=sum(p["count"] for p in items))


@router.get("/{kind}")
async def place_detail(request: Request, kind: str, key: str = "", user=Depends(get_current_user),
                       db=Depends(get_db)):
    if kind not in places.KINDS:
        raise NotFoundError("Místo nenalezeno.")
    service = VehicleService(db)
    items = places.visits(db, kind, service.get_accessible_ids(user), key)
    if not items:
        raise NotFoundError("Místo nenalezeno.")
    summary = places.detail(items)
    volume, avg_price = places.fuel_volume(items) if kind == "station" else ({}, None)
    return render(request, "places/detail.html", kind=kind, kind_label=places.KIND_LABELS[kind],
                  kinds=places.KINDS, summary=summary, visits=items, volume=volume, avg_price=avg_price,
                  editable_ids=set(service.get_accessible_ids(user, ROLE_EDITOR)))
