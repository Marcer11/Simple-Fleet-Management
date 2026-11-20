from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from services.config import LOCAL_CURRENCY
from services.errors import ValidationError
from services.exchange_rate import get_rate, ExchangeRateError

Q3 = Decimal("0.001")
Q2 = Decimal("0.01")


def to_decimal(value, quant=None):
    if value is None or value == "":
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value).replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        raise ValidationError(f"Neplatné číslo: {value}")
    if quant is not None:
        result = result.quantize(quant, rounding=ROUND_HALF_UP)
    return result


def normalize_currency(currency_code):
    code = (currency_code or LOCAL_CURRENCY).strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValidationError("Měna musí být třípísmenný kód (např. CZK, EUR).")
    return code


def resolve_rate(currency_code, on_date, manual_rate=None):
    """Kurz do CZK - ruční, nebo z ČNB. Při chybě vyhodí ValidationError s výzvou k ručnímu zadání."""
    if currency_code == LOCAL_CURRENCY:
        return Decimal("1")
    if manual_rate is not None:
        manual_rate = to_decimal(manual_rate)
        if manual_rate <= 0:
            raise ValidationError("Kurz musí být větší než nula.")
        return manual_rate
    try:
        return get_rate(currency_code, on_date)
    except ExchangeRateError as e:
        raise ValidationError(f"{e} Zadejte kurz ručně.")


def convert_price(price_paid, currency_code, on_date, manual_rate=None):
    """Vrátí (měna, cena v původní měně, cena v CZK)."""
    currency_code = normalize_currency(currency_code)
    price_paid = to_decimal(price_paid, Q3)
    if price_paid is None:
        return currency_code, None, None
    if price_paid < 0:
        raise ValidationError("Cena nemůže být záporná.")
    rate = resolve_rate(currency_code, on_date, manual_rate)
    return currency_code, price_paid, (price_paid * rate).quantize(Q3, rounding=ROUND_HALF_UP)


def fuel_prices(volume, unit_price, total_price, currency_code, on_date, manual_rate=None):
    """
    Dopočítá ceny tankování. Stačí zadat cenu za jednotku NEBO celkovou cenu.
    Vrací dict s klíči unit_price, price_paid, currency_code, unit_price_local, price_local.
    """
    volume = to_decimal(volume)
    unit_price = to_decimal(unit_price)
    total_price = to_decimal(total_price)
    currency_code = normalize_currency(currency_code)

    if volume is None or volume <= 0:
        raise ValidationError("Množství paliva musí být větší než nula.")
    if unit_price is None and total_price is None:
        raise ValidationError("Zadejte cenu za jednotku nebo celkovou cenu.")
    if (unit_price is not None and unit_price < 0) or (total_price is not None and total_price < 0):
        raise ValidationError("Cena nemůže být záporná.")

    if total_price is None:
        total_price = unit_price * volume
    if unit_price is None:
        unit_price = total_price / volume

    rate = resolve_rate(currency_code, on_date, manual_rate)

    return {
        "unit_price": unit_price.quantize(Q3, rounding=ROUND_HALF_UP),
        "price_paid": total_price.quantize(Q3, rounding=ROUND_HALF_UP),
        "currency_code": currency_code,
        "unit_price_local": (unit_price * rate).quantize(Q3, rounding=ROUND_HALF_UP),
        "price_local": (total_price * rate).quantize(Q3, rounding=ROUND_HALF_UP),
    }
