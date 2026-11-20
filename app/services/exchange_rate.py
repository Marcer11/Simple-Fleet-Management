from datetime import date, datetime
from decimal import Decimal
import threading

import requests

CNB_URL = "https://api.cnb.cz/cnbapi/exrates/daily"
TIMEOUT_SECONDS = 10

_cache = {}
_cache_lock = threading.Lock()


class ExchangeRateError(Exception):
    """Kurz se nepodařilo získat."""


def _to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _fetch_rates(on_date):
    """Vrátí {kód_měny: (množství, kurz)} z kurzovního lístku ČNB pro dané datum."""
    try:
        response = requests.get(
            CNB_URL,
            params={"date": on_date.isoformat(), "lang": "CZ"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise ExchangeRateError(f"Nepodařilo se spojit s ČNB: {e}") from e

    if response.status_code != 200:
        raise ExchangeRateError(
            f"Nepodařilo se získat kurzovní lístek z ČNB (HTTP {response.status_code})."
        )

    try:
        data = response.json()
        return {
            rate["currencyCode"]: (Decimal(str(rate["amount"])), Decimal(str(rate["rate"])))
            for rate in data["rates"]
        }
    except (ValueError, KeyError, TypeError) as e:
        raise ExchangeRateError("Neočekávaná odpověď z ČNB.") from e


def get_rate(currency_code, on_date):
    """Kurz: kolik CZK stojí 1 jednotka dané měny k danému datu."""
    currency_code = currency_code.strip().upper()
    if currency_code == "CZK":
        return Decimal("1")

    on_date = _to_date(on_date)
    if on_date > date.today():
        raise ExchangeRateError("Kurz ČNB pro budoucí datum není k dispozici.")

    with _cache_lock:
        rates = _cache.get(on_date)
    if rates is None:
        rates = _fetch_rates(on_date)
        # Dnešní kurz se může během dne změnit (vyhlašuje se ve 14:30) - necachujeme
        if on_date < date.today():
            with _cache_lock:
                _cache[on_date] = rates

    if currency_code not in rates:
        raise ExchangeRateError(
            f"V kurzovním lístku ČNB nebyl nalezen kurz pro měnu {currency_code} k datu {on_date:%d.%m.%Y}."
        )
    amount, rate = rates[currency_code]
    return rate / amount


def convert_to_czk(amount, currency_code, on_date):
    return Decimal(str(amount)) * get_rate(currency_code, on_date)


class ExchangeRate:
    """Původní rozhraní používané konzolovou aplikací."""

    def __init__(self, date, currency_code: str, amount: float):
        self.date = date
        self.currency_code = currency_code.upper()
        self.amount = amount

    def ConvertToCZK(self):
        try:
            rate = get_rate(self.currency_code, self.date)
        except ExchangeRateError as e:
            raise ValueError(str(e)) from e
        print(f"Načtený kurz ČNB: 1 {self.currency_code} = {rate:.4f} CZK")
        return float(Decimal(str(self.amount)) * rate)
