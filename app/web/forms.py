"""Zpracování a validace hodnot z HTML formulářů."""
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from services.errors import ValidationError


class FormReader:
    """
    Čte hodnoty z formuláře, převádí typy a sbírá chyby.
    Po načtení všech polí zavolejte check() - vyhodí ValidationError se všemi chybami.
    """

    def __init__(self, form):
        self.raw = {key: value for key, value in form.items() if key != "csrf_token"}
        self.errors = []

    @property
    def values(self):
        """Původní hodnoty pro znovuvyplnění formuláře."""
        return dict(self.raw)

    def _get(self, name):
        value = self.raw.get(name)
        if isinstance(value, str):
            value = value.strip()
        return value if value not in (None, "") else None

    def _error(self, message):
        self.errors.append(message)
        return None

    def str(self, name, label, required=False, max_len=None):
        value = self._get(name)
        if value is None:
            return self._error(f"{label}: povinná položka.") if required else None
        if max_len and len(value) > max_len:
            return self._error(f"{label}: nejvýše {max_len} znaků.")
        return value

    def int(self, name, label, required=False, min_value=None, max_value=None):
        value = self._get(name)
        if value is None:
            return self._error(f"{label}: povinná položka.") if required else None
        try:
            number = int(value.replace(" ", "").replace(" ", ""))
        except ValueError:
            return self._error(f"{label}: zadejte celé číslo.")
        if min_value is not None and number < min_value:
            return self._error(f"{label}: minimální hodnota je {min_value}.")
        if max_value is not None and number > max_value:
            return self._error(f"{label}: maximální hodnota je {max_value}.")
        return number

    def decimal(self, name, label, required=False, min_value=None, positive=False):
        value = self._get(name)
        if value is None:
            return self._error(f"{label}: povinná položka.") if required else None
        try:
            number = Decimal(value.replace(" ", "").replace(" ", "").replace(",", "."))
        except InvalidOperation:
            return self._error(f"{label}: zadejte číslo.")
        if not number.is_finite():
            return self._error(f"{label}: zadejte číslo.")
        if positive and number <= 0:
            return self._error(f"{label}: musí být větší než nula.")
        if min_value is not None and number < min_value:
            return self._error(f"{label}: minimální hodnota je {min_value}.")
        return number

    def date(self, name, label, required=False):
        value = self._get(name)
        if value is None:
            return self._error(f"{label}: povinná položka.") if required else None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return self._error(f"{label}: neplatné datum.")

    def time(self, name, label, required=False):
        value = self._get(name)
        if value is None:
            return self._error(f"{label}: povinná položka.") if required else None
        try:
            return time.fromisoformat(value)
        except ValueError:
            return self._error(f"{label}: neplatný čas.")

    def bool(self, name):
        return self._get(name) in ("on", "1", "true", "yes")

    def choice(self, name, label, options, required=False, default=None):
        value = self._get(name) or default
        if value is None:
            return self._error(f"{label}: povinná položka.") if required else None
        if value not in options:
            return self._error(f"{label}: neplatná hodnota.")
        return value

    def check(self):
        if self.errors:
            raise ValidationError(" ".join(self.errors), self.errors)


def parse_filter_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def parse_filter_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def iso(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def rate_from_record(record):
    """Kurz použitý u uloženého záznamu (pro předvyplnění při úpravě)."""
    if record.currency_code and record.currency_code != "CZK" and record.price_paid and record.price_local:
        return iso((Decimal(record.price_local) / Decimal(record.price_paid)).quantize(Decimal("0.0001")))
    return ""
