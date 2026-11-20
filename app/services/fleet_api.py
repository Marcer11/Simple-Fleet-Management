"""API evidence pro aplikaci Timeline: klíče uživatelů a tankování vozidla podle SPZ.

Klíč se ukáže jen jednou po vygenerování, v databázi je uložen jen jeho SHA-256
(klíč je náhodný, pomalé hashování jako u hesla není potřeba). Klíč ani odpovědi se nelogují.
"""
import hashlib
import re
import secrets
from datetime import datetime

from sqlalchemy.orm import joinedload

from models import FuelRecord, User
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


def vehicle_json(vehicle):
    return {"plate": normalize_plate(vehicle.license_plate),
            "name": f"{vehicle.brand} {vehicle.model}".strip()}
