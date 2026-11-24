from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from services.maintenance_service import collect_alerts
from services.stats_service import StatsService
from services.vehicle_service import VehicleService
from models.vehicle import ROLE_EDITOR
from web.deps import get_db, get_current_user, render, TEMPLATES_DIR
from web.routers.events import timeline_context

router = APIRouter()
STATIC_DIR = TEMPLATES_DIR.parent / "static"


@router.get("/")
async def dashboard(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    """Výchozí obrazovka: upozornění a pod nimi časová osa (filtr je skrytý)."""
    vehicle_service = VehicleService(db)
    active = vehicle_service.get_vehicles_for_user(user, only_active=True)
    year = date.today().year
    year_costs = StatsService(db).year_costs([v.id for v in active], year)
    timeline = timeline_context(request, db, user)
    return render(request, "dashboard.html", alerts=collect_alerts(db, active), active=active, year=year,
                  total_year_cost=sum(year_costs.values(), 0),
                  editable=vehicle_service.get_accessible_ids(user, ROLE_EDITOR), **timeline)


# ----------------------------------------------------------------------
# PWA - manifest a service worker musí být v kořeni webu (scope "/")
# ----------------------------------------------------------------------

@router.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/sw.js")
async def service_worker():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@router.get("/offline")
async def offline(request: Request):
    return render(request, "offline.html")


@router.get("/healthz")
async def health():
    return Response("ok", media_type="text/plain")
