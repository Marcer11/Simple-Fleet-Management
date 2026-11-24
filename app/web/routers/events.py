"""Časová osa - všechny události vozidel v čase."""
from fastapi import APIRouter, Depends, Request

from models.vehicle import ROLE_EDITOR
from services.events import KINDS, collect_events, group_by_month
from services.vehicle_service import VehicleService
from web.common import visible_vehicles, default_filter_period
from web.deps import get_db, get_current_user, render
from web.forms import iso, parse_filter_date, parse_filter_int

router = APIRouter()

MONTHS = ["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen", "září", "říjen",
          "listopad", "prosinec"]


@router.get("/timeline")
async def timeline_page(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    q = request.query_params
    vehicles = visible_vehicles(db, user)
    vehicle_id = parse_filter_int(q.get("vehicle_id"))
    selected = [v for v in vehicles if vehicle_id in (None, v.id)]
    if q.get("all"):
        date_from = date_to = None
    else:
        date_from, date_to = default_filter_period(parse_filter_date(q.get("date_from")),
                                                   parse_filter_date(q.get("date_to")))
    kinds = [k for k in q.getlist("kind") if k in KINDS] or list(KINDS)
    events = collect_events(db, selected, date_from, date_to, kinds)
    filters = {"vehicle_id": vehicle_id, "date_from": iso(date_from), "date_to": iso(date_to),
               "all": q.get("all", ""), "kinds": kinds}
    return render(request, "timeline.html", vehicles=vehicles, filters=filters, kinds=KINDS,
                  groups=group_by_month(events), count=len(events), months=MONTHS,
                  show_vehicle=len(selected) > 1,
                  editable_ids=set(VehicleService(db).get_accessible_ids(user, ROLE_EDITOR)),
                  vehicle=selected[0] if vehicle_id and selected else None)
