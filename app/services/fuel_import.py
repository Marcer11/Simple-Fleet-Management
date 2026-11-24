"""
Import tankování z CSV.

Sloupce (v tomto pořadí, oddělené středníkem, první řádek může být záhlaví):
datum; čas; cena; měna; množství; tachometr; pumpa; palivo; platba; částečně

- datum: Excelové číslo (46193), "24.11.2026", "24. 11. 2026" nebo "2026-11-24"; může obsahovat i čas
  (Excel 46193,73 nebo "24.11.2026 17:34")
- čas: zlomek dne z Excelu (0,7319) nebo "17:34"
- cena: za jednotku nebo celková (volí se při importu), desetinná čárka i tečka
- měna: prázdná = CZK
- platba: DKV = Tankovací karta, Hotově = Hotovost, ostatní beze změny
- částečně: 1 / ano = nedotankováno do plna, prázdné = do plna
"""
import csv
import io
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from services import timeline

COLUMNS = ["datum", "čas", "cena", "měna", "množství", "tachometr", "pumpa", "palivo", "platba", "částečně"]
EXCEL_EPOCH = date(1899, 12, 30)
PAYMENT_MAP = {"dkv": "Tankovací karta", "hotově": "Hotovost", "hotove": "Hotovost", "hotovost": "Hotovost",
               "karta": "Karta"}
MAX_ROWS = 2000


class ImportRowError(ValueError):
    pass


def _number(value, label, required=False):
    text = re.sub(r"[\s ]", "", value or "").replace(",", ".")
    if not text:
        if required:
            raise ImportRowError(f"chybí {label}")
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ImportRowError(f"{label} „{value.strip()}“ není číslo") from None


def _fraction_time(fraction):
    minutes = int((fraction * 24 * 60).quantize(Decimal("1")))
    minutes = min(max(minutes, 0), 24 * 60 - 1)
    return time(minutes // 60, minutes % 60)


def parse_datetime(date_text, time_text):
    """Datum a čas z importu -> datetime (bez sekund)."""
    date_text = (date_text or "").strip()
    time_text = (time_text or "").strip()
    if not date_text:
        raise ImportRowError("chybí datum")
    day, day_time = None, None
    serial = re.fullmatch(r"\d{4,6}([.,]\d+)?", date_text)
    if serial:  # Excelové pořadové číslo dne (případně i se zlomkem = čas)
        number = Decimal(date_text.replace(",", "."))
        day = EXCEL_EPOCH + timedelta(days=int(number))
        if number % 1:
            day_time = _fraction_time(number % 1)
    else:
        m = re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::\d{2})?)?", date_text) \
            or re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2})(?::\d{2})?)?", date_text)
        if not m:
            raise ImportRowError(f"neznámý formát data „{date_text}“")
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            day = date(a, b, c) if a > 31 else date(c, b, a)
        except ValueError:
            raise ImportRowError(f"neplatné datum „{date_text}“") from None
        if m.group(4):
            day_time = time(int(m.group(4)), int(m.group(5)))
    if time_text:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", time_text)
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            day_time = time(int(m.group(1)), int(m.group(2)))
        else:
            fraction = _number(time_text, "čas")
            if fraction is None or not (0 <= fraction < 1):
                raise ImportRowError(f"neznámý formát času „{time_text}“")
            day_time = _fraction_time(fraction)
    if day_time is None:
        raise ImportRowError("chybí čas")
    return datetime.combine(day, day_time)


def _payment(value):
    value = (value or "").strip()
    return PAYMENT_MAP.get(value.lower(), value[:20]) or None


def _partial(value):
    return (value or "").strip().lower() in ("1", "ano", "a", "yes", "true", "x")


def _is_header(cells):
    return bool(cells) and (cells[0] or "").strip().lower().startswith("dat")


def parse_csv(content, price_is_total=False):
    """Text CSV -> (řádky, chyby). Řádek je dict připravený k náhledu a uložení."""
    if isinstance(content, bytes):
        for encoding in ("utf-8-sig", "cp1250"):
            try:
                content = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            return [], ["Soubor nejde přečíst (očekává se UTF-8 nebo Windows-1250)."]
    first = content.split("\n", 1)[0]
    delimiter = ";" if ";" in first or "," not in first else ","
    rows, errors = [], []
    for number, cells in enumerate(csv.reader(io.StringIO(content), delimiter=delimiter), start=1):
        if not any((c or "").strip() for c in cells):
            continue
        if number == 1 and _is_header(cells):
            continue
        if len(rows) >= MAX_ROWS:
            errors.append(f"Najednou lze importovat nejvýše {MAX_ROWS} řádků.")
            break
        cells = (cells + [""] * len(COLUMNS))[:len(COLUMNS)]
        values = dict(zip(COLUMNS, cells))
        try:
            at = parse_datetime(values["datum"], values["čas"])
            price = _number(values["cena"], "cena", required=True)
            volume = _number(values["množství"], "množství", required=True)
            odometer = _number(values["tachometr"], "tachometr", required=True)
            if volume <= 0:
                raise ImportRowError("množství musí být větší než nula")
            if price < 0 or odometer < 0:
                raise ImportRowError("cena ani tachometr nemohou být záporné")
            fuel = " ".join((values["palivo"] or "").split())
            if not fuel:
                raise ImportRowError("chybí palivo")
            rows.append({
                "line": number,
                "at": at,
                "unit_price": None if price_is_total else price,
                "total_price": price if price_is_total else None,
                "currency": (values["měna"] or "").strip().upper() or "CZK",
                "volume": volume,
                "odometer": int(odometer),
                "station": " ".join((values["pumpa"] or "").split())[:100] or None,
                "address": None,
                "fuel": fuel[:30],
                "payment": _payment(values["platba"]),
                "full_tank": not _partial(values["částečně"]),
                "from_timeline": False,
            })
        except ImportRowError as e:
            errors.append(f"Řádek {number}: {e}.")
    rows.sort(key=lambda r: (r["at"], r["odometer"]))
    return rows, errors


def lookup_stations(rows, api_key):
    """Dohledá pumpu každého řádku v Timeline; nenalezená zůstane z importu (bez adresy).

    Vrací text upozornění, pokud Timeline nešla použít (neplatný klíč, nedostupnost).
    """
    if not (timeline.is_enabled() and api_key):
        return None
    for row in rows:
        try:
            stop = timeline.find_fuel_stop(api_key, row["at"])
        except timeline.TimelineError as e:
            return f"Pumpy se z Timeline nepodařilo dohledat: {e}"
        if stop:
            row["station"], row["address"], row["from_timeline"] = stop["name"], stop["address"] or None, True
    return None


def to_payload(rows):
    """Řádky -> JSON-serializovatelná data (skryté pole formuláře mezi náhledem a uložením)."""
    return [{**r, "at": r["at"].strftime("%Y-%m-%dT%H:%M"),
             "unit_price": None if r["unit_price"] is None else str(r["unit_price"]),
             "total_price": None if r["total_price"] is None else str(r["total_price"]),
             "volume": str(r["volume"])} for r in rows]


def from_payload(items):
    rows = []
    for item in items:
        rows.append({**item, "at": datetime.strptime(item["at"], "%Y-%m-%dT%H:%M"),
                     "unit_price": Decimal(item["unit_price"]) if item.get("unit_price") else None,
                     "total_price": Decimal(item["total_price"]) if item.get("total_price") else None,
                     "volume": Decimal(item["volume"])})
    return rows
