from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from services.maintenance_service import collect_alerts
from services.stats_service import StatsService
from services.vehicle_service import VehicleService
from web.deps import get_db, get_current_user, render, TEMPLATES_DIR

router = APIRouter()
STATIC_DIR = TEMPLATES_DIR.parent / "static"


@router.get("/")
async def dashboard(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    vehicle_service = VehicleService(db)
    stats = StatsService(db)
    vehicles = vehicle_service.get_vehicles_for_user(user, only_active=True)
    ids = [v.id for v in vehicles]
    year = date.today().year
    year_costs = stats.year_costs(ids, year)
    alerts = collect_alerts(db, vehicles)

    cards = [{
        "vehicle": v,
        "odometer": vehicle_service.get_current_odometer(v.id),
        "consumption": stats.avg_consumption(v.id),
        "year_cost": year_costs.get(v.id),
        "alerts": [a for a in alerts if a.vehicle.id == v.id],
    } for v in vehicles]

    return render(request, "dashboard.html", cards=cards, alerts=alerts, year=year,
                  roles=vehicle_service.get_roles_for_user(user),
                  total_year_cost=sum(year_costs.values(), 0))


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
