"""API evidence pro aplikaci Timeline: klíče uživatelů a tankování vozidla podle SPZ.

Klíč se ukáže jen jednou po vygenerování, v databázi je uložen jen jeho SHA-256
(klíč je náhodný, pomalé hashování jako u hesla není potřeba). Klíč ani odpovědi se nelogují.
"""
import hashlib
import re
import secrets
from datetime import datetime

from sqlalchemy.orm import joinedload

from models import FuelRecord, User, VehicleNote
from services.errors import NotFoundError, ValidationError
from services.vehicle_service import VehicleService, normalize_plate

KEY_PREFIX = "fk_"
KEY_RE = re.compile(r"^fk_[A-Za-z0-9_\-]{43}$")  # fk_ + 32 B v base64url


def hash_key(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_key(session, user):
    """Vygeneruje nový klíč (starý tím přestane platit) a vrátí ho - jen tentokrát."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    user.api_key_hash = hash_key(key)
    user.api_key_created_at = datetime.now().replace(microsecond=0)
    session.commit()
    return key


def revoke_key(session, user):
    user.api_key_hash = None
    user.api_key_created_at = None
    session.commit()


def user_for_key(session, key):
    """Aktivní uživatel s daným klíčem, jinak None."""
    if not key or not KEY_RE.match(key):
        return None
    user = session.query(User).filter(User.api_key_hash == hash_key(key)).first()
    return user if user is not None and user.is_active else None


def bearer_token(authorization):
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else None


def parse_local_datetime(value, end_of_day=False):
    """Místní čas ISO 8601 bez časové zóny; samotné datum = začátek (nebo konec) dne."""
    value = (value or "").strip()
    if not value:
        raise ValidationError("chybí čas")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"neplatný čas: {value[:40]}") from None
    if parsed.tzinfo is not None:
        raise ValidationError("čas musí být místní, bez časové zóny")
    if end_of_day and len(value) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed


def find_vehicle(session, user, plate):
    """Vozidlo uživatele (vlastní i sdílené) podle normalizované SPZ.

    SPZ nejsou unikátní napříč historií (prodané auto, opakovaně půjčené auto z půjčovny),
    přednost má aktivní vozidlo, pak naposledy založené.
    """
    wanted = normalize_plate(plate)
    if not wanted:
        raise ValidationError("chybí SPZ")
    matches = [v for v in VehicleService(session).get_vehicles_for_user(user)
               if normalize_plate(v.license_plate) == wanted]
    if not matches:
        raise NotFoundError("vozidlo nenalezeno")
    return max(matches, key=lambda v: (bool(v.is_active), v.id))


def _boundary(session, vehicle_id, condition, order):
    """Čas nejbližšího tankování do plna před/po hranici, nebo None."""
    row = (session.query(FuelRecord.refuel_datetime)
           .filter(FuelRecord.vehicle_id == vehicle_id, FuelRecord.full_tank.is_(True), condition)
           .order_by(order).first())
    return row[0] if row else None


def refuels(session, vehicle, date_from, date_to, full_context=False):
    """Tankování vozidla v rozsahu [date_from, date_to] (všech uživatelů), vzestupně.

    full_context rozšíří rozsah o úsek od posledního tankování do plna před date_from
    a do prvního tankování do plna po date_to (včetně nich), pokud existují.
    """
    start, end = date_from, date_to
    if full_context:
        before = _boundary(session, vehicle.id, FuelRecord.refuel_datetime < date_from,
                           FuelRecord.refuel_datetime.desc())
        after = _boundary(session, vehicle.id, FuelRecord.refuel_datetime > date_to,
                          FuelRecord.refuel_datetime.asc())
        start = before or start
        end = after or end
    return (session.query(FuelRecord)
            .options(joinedload(FuelRecord.created_by))
            .filter(FuelRecord.vehicle_id == vehicle.id,
                    FuelRecord.refuel_datetime >= start,
                    FuelRecord.refuel_datetime <= end)
            .order_by(FuelRecord.refuel_datetime, FuelRecord.id)
            .all())


def _number(value):
    return float(value) if value is not None else None


def refuel_json(record):
    return {
        "id": str(record.id),
        "time": record.refuel_datetime.replace(microsecond=0).isoformat(),
        "odometer": record.odometer,
        "quantity": _number(record.volume_liters),
        "unit": record.unit,
        "fuel_type": record.fuel_type,
        "price_total": _number(record.price_paid),
        "currency": (record.currency_code or "CZK").upper(),
        "price_czk": _number(record.price_local),
        "full": bool(record.full_tank),
        "station_name": record.station_name,
        "station_address": record.station_address,
        "fueled_by": record.created_by.name if record.created_by else None,
    }


def _iso(value):
    return value.isoformat() if value is not None else None


def _status(vehicle):
    if vehicle.is_sold:
        return "sold"
    if vehicle.is_returned:
        return "returned"
    return "active" if vehicle.is_active else "inactive"


def vehicles(session, user, only_active=True):
    """Vozidla uživatele (vlastní i sdílená) s údaji pro API, seřazená podle značky a modelu."""
    service = VehicleService(session)
    items = service.get_vehicles_for_user(user, only_active=only_active)
    ids = [v.id for v in items]
    roles = service.get_roles_for_user(user)
    vignettes = service.vignette_status(items)
    last_dates = service.last_record_dates(items)
    fuel_types = {}
    if ids:
        rows = (session.query(FuelRecord.vehicle_id, FuelRecord.fuel_type)
                .filter(FuelRecord.vehicle_id.in_(ids)).distinct())
        for vid, fuel in rows:
            fuel_types.setdefault(vid, []).append(fuel)
    notes = {}
    if ids:
        query = (session.query(VehicleNote).options(joinedload(VehicleNote.created_by))
                 .filter(VehicleNote.vehicle_id.in_(ids))
                 .order_by(VehicleNote.note_datetime.desc(), VehicleNote.id.desc()))
        for n in query:
            notes.setdefault(n.vehicle_id, []).append({
                "id": str(n.id),
                "time": n.note_datetime.replace(microsecond=0).isoformat(),
                "odometer": n.odometer,
                "category": n.category,
                "text": n.text,
                "author": n.created_by.name if n.created_by else None,
            })
    from services.stats_service import StatsService
    stats = StatsService(session)
    result = []
    for v in sorted(items, key=lambda v: (not v.in_use, v.brand.lower(), v.model.lower(), v.id)):
        vignette = vignettes.get(v.id)
        rental = v.last_rental if v.is_rental else None
        result.append({
            "id": str(v.id),
            "plate": normalize_plate(v.license_plate),
            "name": f"{v.brand} {v.model}".strip(),
            "brand": v.brand,
            "model": v.model,
            "kind": v.kind or "car",
            "production_year": v.production_year,
            "engine_volume": v.engine_volume,
            "engine_power": v.engine_power,
            "fuel": v.fuel,
            "alt_fuel": v.alt_fuel,
            "color": v.color,
            "color_hex": v.color_hex,
            "vin": v.vin,
            "active": v.in_use,
            "status": _status(v),
            "role": roles.get(v.id),
            "owner": v.owner.name if v.owner else None,
            "odometer": service.get_current_odometer(v.id),
            "fuel_types": sorted(fuel_types.get(v.id, [])),
            "consumption": [{"fuel": fuel, "value": round(float(info["value"]), 2), "unit": info["unit"]}
                            for fuel, info in stats.avg_consumption(v.id).items()],
            "tire_sizes": v.tire_size_list,
            "purchase": {"date": _iso(v.purchase_date), "odometer": v.purchase_odometer,
                         "price_czk": _number(v.purchase_price)},
            "sale": {"date": _iso(v.sale_date), "odometer": v.sale_odometer, "price_czk": _number(v.sale_price)},
            "vignette": {"status": vignette[0], "date": _iso(vignette[1])} if vignette else None,
            "is_rental": bool(v.is_rental),
            "lender": v.lender,
            "out_of_order": {"since": _iso(v.out_of_order_since), "reason": v.out_of_order_reason}
            if v.out_of_order else None,
            "rental": {
                "from": _iso(datetime.combine(rental.date_from, rental.time_from) if rental.time_from
                             else rental.date_from),
                "to": _iso(datetime.combine(rental.date_to, rental.time_to) if rental.date_to and rental.time_to
                           else rental.date_to),
            } if rental else None,
            "last_record": _iso(last_dates.get(v.id)),
            "note": v.note,
            "notes": notes.get(v.id, []),
        })
    return result


def vehicle_json(vehicle):
    return {"plate": normalize_plate(vehicle.license_plate),
            "name": f"{vehicle.brand} {vehicle.model}".strip()}
