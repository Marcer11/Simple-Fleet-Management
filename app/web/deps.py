"""Sdílené závislosti webové aplikace: DB session, přihlášený uživatel, šablony, CSRF, flash zprávy."""
import secrets
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from starlette.templating import Jinja2Templates

from models.fuel_record import FUEL_CATEGORIES
from models.vehicle import ROLE_LEVELS, SHARE_ROLES
from services import db as db_module
from services.user_service import UserService

TEMPLATES_DIR = Path(__file__).parent / "templates"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


# ----------------------------------------------------------------------
# Databáze
# ----------------------------------------------------------------------

def get_db():
    """Vrátí session pro komunikaci s databází (po požadavku ji zavře)."""
    session = db_module.SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ----------------------------------------------------------------------
# Přihlášení
# ----------------------------------------------------------------------

class LoginRequired(Exception):
    """Vyhozeno, pokud stránka vyžaduje přihlášení - obslouží se přesměrováním na /login."""


def get_optional_user(request: Request, db=Depends(get_db)):
    user_id = request.session.get("user_id")
    user = UserService(db).get_user(user_id) if user_id else None
    if user is not None and not user.is_active:
        user = None
    request.state.user = user
    return user


def get_current_user(request: Request, user=Depends(get_optional_user)):
    if user is None:
        raise LoginRequired()
    return user


def login_user(request: Request, user):
    # Nová session po přihlášení (ochrana proti session fixation)
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["csrf_token"] = secrets.token_urlsafe(32)


def logout_user(request: Request):
    request.session.clear()


# ----------------------------------------------------------------------
# CSRF
# ----------------------------------------------------------------------

def get_csrf_token(request: Request):
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


async def csrf_protect(request: Request):
    """Každý POST formulář musí obsahovat platný csrf_token."""
    if request.method in SAFE_METHODS:
        return
    form = await request.form()
    sent = form.get("csrf_token") or request.headers.get("x-csrf-token") or ""
    expected = request.session.get("csrf_token") or ""
    if not expected or not secrets.compare_digest(str(sent), expected):
        raise HTTPException(status_code=403, detail="Neplatný bezpečnostní token formuláře. Obnovte stránku a zkuste to znovu.")


# ----------------------------------------------------------------------
# Flash zprávy
# ----------------------------------------------------------------------

def flash(request: Request, message, category="success"):
    flashes = request.session.get("_flashes", [])
    flashes.append([category, message])
    request.session["_flashes"] = flashes


def pop_flashes(request: Request):
    return request.session.pop("_flashes", [])


# ----------------------------------------------------------------------
# Formátování pro šablony
# ----------------------------------------------------------------------

def _group(value_str):
    return value_str.replace(",", " ").replace(".", ",")


def fmt_num(value, decimals=2):
    if value is None or value == "":
        return "–"
    return _group(f"{float(value):,.{decimals}f}")


def fmt_qty(value):
    """Číslo bez zbytečných nul (40,00 -> 40; 40,50 -> 40,5)."""
    if value is None:
        return "–"
    value = Decimal(str(value)).normalize()
    if value == value.to_integral():
        return _group(f"{int(value):,}")
    return _group(f"{value:,f}")


def fmt_czk(value, decimals=2):
    return "–" if value is None else f"{fmt_num(value, decimals)} Kč"


def fmt_money(value, currency="CZK"):
    if value is None:
        return "–"
    return fmt_czk(value) if currency in (None, "CZK") else f"{fmt_num(value)} {currency}"


def fmt_km(value):
    return "–" if value is None else f"{_group(f'{int(value):,}')} km"


def fmt_date(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.day}. {value.month}. {value.year}"


def fmt_datetime(value):
    return f"{fmt_date(value)} {value:%H:%M}" if value else ""


LEVEL_LABELS = {
    "ok": ("V pořádku", "ok"),
    "warning": ("Blíží se", "warning"),
    "overdue": ("Po termínu", "danger"),
    "unknown": ("Nelze určit", "muted"),
}
ROLE_LABELS = {"owner": "Vlastník", **SHARE_ROLES}


def _context(request: Request):
    return {
        "current_user": getattr(request.state, "user", None),
        "csrf_token": get_csrf_token(request),
        "flashes": pop_flashes(request),
        "today": date.today(),
        "path": request.url.path,
        "role_labels": ROLE_LABELS,
        "level_labels": LEVEL_LABELS,
    }


templates = Jinja2Templates(directory=str(TEMPLATES_DIR), context_processors=[_context])
templates.env.filters.update({
    "num": fmt_num,
    "qty": fmt_qty,
    "czk": fmt_czk,
    "money": fmt_money,
    "km": fmt_km,
    "date": fmt_date,
    "datetime": fmt_datetime,
})
templates.env.globals.update({
    "role_level": lambda role: ROLE_LEVELS.get(role, 0),
    "fuel_choices": [(c, c) for c in FUEL_CATEGORIES],  # druhy paliva (formulář vozidla)
})


def render(request: Request, name, status_code=200, **context):
    return templates.TemplateResponse(request, name, context, status_code=status_code)
