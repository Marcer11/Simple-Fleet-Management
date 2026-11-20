import os
import secrets
import warnings
from dotenv import load_dotenv

load_dotenv()


def _bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "ano", "on")


# --- Databáze ---
# DATABASE_URL má přednost (např. sqlite:///fleet.db pro lokální vývoj),
# jinak se URL složí z DB_* proměnných (MySQL).
DATABASE_URL_OVERRIDE = os.getenv("DATABASE_URL")
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = os.getenv("DB_PORT", "3306")

# --- Web ---
SECRET_KEY = os.getenv("SECRET_KEY")
SESSION_HTTPS_ONLY = _bool("SESSION_HTTPS_ONLY", False)
ALLOW_REGISTRATION = _bool("ALLOW_REGISTRATION", True)
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))

# Aplikace Timeline na stejném serveru - dohledání pumpy podle polohy (prázdné = vypnuto)
TIMELINE_URL = (os.getenv("TIMELINE_URL") or "").strip().rstrip("/")

# Domácí měna - kurzy se berou z ČNB, proto CZK
LOCAL_CURRENCY = "CZK"


def validate_config():
    if DATABASE_URL_OVERRIDE:
        return

    missing = []

    if not DB_HOST:
        missing.append("DB_HOST")
    if not DB_USER:
        missing.append("DB_USER")
    if not DB_PASSWORD:
        missing.append("DB_PASSWORD")
    if not DB_NAME:
        missing.append("DB_NAME")

    if missing:
        raise ValueError(f"Chybí proměnné v .env: {', '.join(missing)}")


def get_database_url():
    validate_config()
    if DATABASE_URL_OVERRIDE:
        return DATABASE_URL_OVERRIDE
    # URL.create správně zakóduje i hesla se speciálními znaky (@, %, #, mezera…)
    from sqlalchemy.engine import URL
    url = URL.create(
        "mysql+mysqlconnector",
        username=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=int(DB_PORT),
        database=DB_NAME,
        query={"charset": "utf8mb4"},
    )
    return url.render_as_string(hide_password=False)


def get_secret_key():
    if SECRET_KEY:
        return SECRET_KEY
    warnings.warn(
        "SECRET_KEY není nastaven v .env - používám náhodný klíč, "
        "po restartu aplikace budou všichni uživatelé odhlášeni."
    )
    return secrets.token_urlsafe(32)
