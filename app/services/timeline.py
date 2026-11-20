"""
Klient API aplikace Timeline: u jaké čerpací stanice byl uživatel v čase tankování.

Klíč i odpověď jsou osobní údaje (poloha) - nic z toho se neloguje ani neukládá
mimo vyplněný formulář.
"""
import re

import requests

from services import config

TIMEOUT_SECONDS = 5
DEFAULT_TOLERANCE_MINUTES = 15
KEY_RE = re.compile(r"^tl_[A-Za-z0-9_\-]{10,96}$")


class TimelineError(Exception):
    """Chyba dotazu; `kind` je 'auth' (neplatný klíč), 'request' (špatný dotaz) nebo 'unavailable'."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def is_enabled():
    return bool(config.TIMELINE_URL)


def is_valid_key(key):
    return bool(key) and bool(KEY_RE.match(key))


def _text(value, max_len):
    return (value or "").strip()[:max_len] if isinstance(value, str) else ""


def find_fuel_stop(api_key, at, tolerance=DEFAULT_TOLERANCE_MINUTES):
    """
    Vrátí dict {name, address, arrive, leave, minutes_off} nebo None, pokud uživatel v danou
    dobu u pumpy nebyl. `at` je datetime v místním čase (jako na účtence).
    """
    if not is_enabled():
        raise TimelineError("unavailable", "Napojení na Timeline není nastaveno.")
    if not api_key:
        raise TimelineError("auth", "Nemáte nastavený API klíč Timeline.")
    try:
        response = requests.get(
            f"{config.TIMELINE_URL}/api/fuel-stop",
            params={"at": at.strftime("%Y-%m-%dT%H:%M"), "tolerance": int(tolerance)},
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise TimelineError("unavailable", "Timeline teď není dostupná.") from None

    if response.status_code == 401:
        raise TimelineError("auth", "API klíč Timeline je neplatný nebo zrušený – obnovte ho v profilu.")
    if response.status_code == 400:
        raise TimelineError("request", "Timeline odmítla dotaz (neplatné datum nebo čas).")
    if response.status_code != 200:
        raise TimelineError("unavailable", "Timeline teď není dostupná.")
    try:
        data = response.json()
    except ValueError:
        raise TimelineError("unavailable", "Timeline vrátila neplatnou odpověď.") from None

    if not isinstance(data, dict) or not data.get("found"):
        return None
    name = _text(data.get("name"), 100)
    if not name:
        return None
    address = _text(data.get("address"), 200)
    if not address:
        address = ", ".join(p for p in (_text(data.get("city"), 100), _text(data.get("country"), 10)) if p)
    minutes_off = data.get("minutes_off")
    return {
        "name": name,
        "address": address,
        "arrive": _text(data.get("arrive"), 25),
        "leave": _text(data.get("leave"), 25),
        "minutes_off": minutes_off if isinstance(minutes_off, int) else None,
    }
