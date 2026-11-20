import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from services import config
from services import fleet_api, timeline
from services.errors import ValidationError
from services.user_service import UserService, normalize_email
from web.deps import get_db, get_optional_user, get_current_user, login_user, logout_user, flash, render
from web.forms import FormReader

router = APIRouter()

# Jednoduchá ochrana proti hádání hesel: max. 5 neúspěšných pokusů za 15 minut
MAX_FAILED_ATTEMPTS = 5
ATTEMPT_WINDOW_SECONDS = 15 * 60
_failed_attempts = defaultdict(deque)


def _attempt_key(request, email):
    client = request.client.host if request.client else "?"
    return f"{client}|{normalize_email(email)}"


def _is_blocked(key):
    attempts = _failed_attempts[key]
    now = time.monotonic()
    while attempts and now - attempts[0] > ATTEMPT_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= MAX_FAILED_ATTEMPTS


def _safe_next(url):
    """Povolit jen přesměrování v rámci aplikace."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return "/"


@router.get("/login")
async def login_form(request: Request, next: str = "/", user=Depends(get_optional_user)):
    if user:
        return RedirectResponse(_safe_next(next), status_code=303)
    return render(request, "auth/login.html", next=_safe_next(next), values={},
                  allow_registration=config.ALLOW_REGISTRATION)


@router.post("/login")
async def login_post(request: Request, db=Depends(get_db)):
    form = FormReader(await request.form())
    email = form.raw.get("email", "")
    next_url = _safe_next(form.raw.get("next"))
    key = _attempt_key(request, email)

    def fail(message):
        return render(request, "auth/login.html", status_code=400, error=message, next=next_url,
                      values={"email": email}, allow_registration=config.ALLOW_REGISTRATION)

    if _is_blocked(key):
        return fail("Příliš mnoho neúspěšných pokusů. Zkuste to znovu za 15 minut.")

    user = UserService(db).authenticate(email, form.raw.get("password", ""))
    if user is None:
        _failed_attempts[key].append(time.monotonic())
        return fail("Nesprávný e-mail nebo heslo.")

    _failed_attempts.pop(key, None)
    login_user(request, user)
    flash(request, f"Vítejte, {user.name}!")
    return RedirectResponse(next_url, status_code=303)


@router.post("/logout")
async def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)


@router.get("/register")
async def register_form(request: Request, user=Depends(get_optional_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    if not config.ALLOW_REGISTRATION:
        return render(request, "auth/register.html", status_code=403, disabled=True, values={})
    return render(request, "auth/register.html", values={})


@router.post("/register")
async def register_post(request: Request, db=Depends(get_db)):
    if not config.ALLOW_REGISTRATION:
        return render(request, "auth/register.html", status_code=403, disabled=True, values={})
    form = FormReader(await request.form())
    try:
        user = UserService(db).create_user(
            form.raw.get("email"), form.raw.get("name"),
            form.raw.get("password", ""), form.raw.get("password_confirm", ""),
        )
    except ValidationError as e:
        values = {k: v for k, v in form.values.items() if "password" not in k}
        return render(request, "auth/register.html", status_code=400, error=str(e), values=values)
    login_user(request, user)
    flash(request, "Účet byl vytvořen. Začněte přidáním vozidla.")
    return RedirectResponse("/vehicles/add", status_code=303)


@router.get("/profile")
async def profile(request: Request, user=Depends(get_current_user)):
    return render(request, "auth/profile.html", values={"name": user.name},
                  timeline_enabled=timeline.is_enabled())


@router.post("/profile")
async def profile_post(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    form = FormReader(await request.form())
    service = UserService(db)
    try:
        if form.raw.get("action") == "password":
            service.change_password(user, form.raw.get("current_password", ""),
                                    form.raw.get("new_password", ""), form.raw.get("new_password_confirm", ""))
            flash(request, "Heslo bylo změněno.")
        elif form.raw.get("action") == "timeline":
            service.set_timeline_key(user, form.raw.get("timeline_api_key"))
            flash(request, "API klíč Timeline byl uložen." if user.timeline_api_key else "API klíč Timeline byl odebrán.")
        elif form.raw.get("action") == "timeline_remove":
            service.set_timeline_key(user, None)
            flash(request, "API klíč Timeline byl odebrán.")
        elif form.raw.get("action") == "api_key_generate":
            # klíč se ukáže jen v této odpovědi (bez přesměrování, neukládá se do session)
            new_key = fleet_api.generate_key(db, user)
            response = render(request, "auth/profile.html", values={"name": user.name},
                              timeline_enabled=timeline.is_enabled(), new_api_key=new_key)
            response.headers["Cache-Control"] = "no-store"
            return response
        elif form.raw.get("action") == "api_key_revoke":
            fleet_api.revoke_key(db, user)
            flash(request, "API klíč pro Timeline byl zrušen.")
        else:
            service.update_profile(user, form.raw.get("name"))
            flash(request, "Profil byl uložen.")
    except ValidationError as e:
        return render(request, "auth/profile.html", status_code=400, error=str(e),
                      values={"name": form.raw.get("name", user.name)}, timeline_enabled=timeline.is_enabled())
    return RedirectResponse("/profile", status_code=303)
