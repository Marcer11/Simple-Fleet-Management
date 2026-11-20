"""JSON API pro aplikaci Timeline (přihlášení klíčem v hlavičce Authorization: Bearer)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from services import fleet_api
from services.errors import NotFoundError, ValidationError
from web.deps import get_db

router = APIRouter(prefix="/api")


def _json(data, status_code=200):
    # tankování a jména uživatelů - nic necachovat
    return JSONResponse(data, status_code=status_code, headers={"Cache-Control": "no-store"})


def _error(status_code, message):
    response = _json({"error": message}, status_code)
    if status_code == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


@router.get("/refuels")
async def api_refuels(request: Request, db=Depends(get_db)):
    """Tankování vozidla podle SPZ za období (viz readme, Napojení na Timeline)."""
    user = fleet_api.user_for_key(db, fleet_api.bearer_token(request.headers.get("authorization")))
    if user is None:
        return _error(401, "chybí nebo neplatný API klíč")
    q = request.query_params
    try:
        date_from = fleet_api.parse_local_datetime(q.get("from"))
        date_to = fleet_api.parse_local_datetime(q.get("to"), end_of_day=True)
        if date_from > date_to:
            raise ValidationError("from je později než to")
        context = (q.get("context") or "").strip().lower()
        if context not in ("", "full"):
            raise ValidationError("context může být jen „full“")
        vehicle = fleet_api.find_vehicle(db, user, q.get("plate"))
        records = fleet_api.refuels(db, vehicle, date_from, date_to, full_context=context == "full")
    except ValidationError as e:
        return _error(400, str(e))
    except NotFoundError as e:
        return _error(404, str(e))
    return _json({"vehicle": fleet_api.vehicle_json(vehicle),
                  "refuels": [fleet_api.refuel_json(r) for r in records]})
