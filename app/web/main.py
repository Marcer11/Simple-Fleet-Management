from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from services import config
from services.errors import NotFoundError, PermissionDeniedError
from web.deps import LoginRequired, csrf_protect, render
from web.routers import api, auth, dashboard, events, fuel, fuel_types, maintenance, stats, tires, vehicles

app = FastAPI(
    title="Simple Fleet Manager",
    dependencies=[Depends(csrf_protect)],
    docs_url=None, redoc_url=None, openapi_url=None,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=config.get_secret_key(),
    session_cookie="sfm_session",
    max_age=30 * 24 * 3600,
    same_site="lax",
    https_only=config.SESSION_HTTPS_ONLY,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(vehicles.router)
app.include_router(fuel.router)
app.include_router(fuel_types.router)
app.include_router(maintenance.router)
app.include_router(stats.router)
app.include_router(events.router)
app.include_router(tires.router)
app.include_router(api.router)


# ----------------------------------------------------------------------
# Obsluha chyb
# ----------------------------------------------------------------------

@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    target = request.url.path
    if request.url.query:
        target += "?" + request.url.query
    if request.method != "GET":
        target = "/"
    return RedirectResponse(f"/login?next={quote(target)}", status_code=303)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return render(request, "error.html", status_code=404, title="Nenalezeno", message=str(exc))


@app.exception_handler(PermissionDeniedError)
async def permission_handler(request: Request, exc: PermissionDeniedError):
    return render(request, "error.html", status_code=403, title="Přístup odepřen", message=str(exc))


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    titles = {403: "Přístup odepřen", 404: "Stránka nenalezena", 405: "Nepovolená metoda"}
    message = exc.detail if exc.status_code != 404 else "Požadovaná stránka neexistuje."
    return render(request, "error.html", status_code=exc.status_code,
                  title=titles.get(exc.status_code, "Chyba"), message=message)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return render(request, "error.html", status_code=400, title="Neplatný požadavek",
                  message="Odeslaná data nejsou platná.")
