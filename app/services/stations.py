"""Přehled čerpacích stanic: značka -> konkrétní stanice (adresa), počet tankování a útrata."""
import re
from collections import defaultdict
from decimal import Decimal

ZERO = Decimal("0")
UNKNOWN = "Neuvedeno"

# (vzor v názvu stanice, značka) - první shoda vyhrává
_BRANDS = [
    (r"orlen|benzina", "ORLEN"),
    (r"\bmol\b", "MOL"),
    (r"\bomv\b", "OMV"),
    (r"\bshell\b", "Shell"),
    (r"euro\s?oil", "EuroOil"),
    (r"robin\s?oil", "Robin Oil"),
    (r"tank\s?ono|\bono\b", "Tank ONO"),
    (r"circle\s?k", "Circle K"),
    (r"total", "TotalEnergies"),
    (r"\bagip\b|\beni\b", "Eni"),
    (r"\bglobus\b", "Globus"),
    (r"\btesco\b", "Tesco"),
    (r"\bkaufland\b", "Kaufland"),
    (r"\bmakro\b", "Makro"),
    (r"\bprim\b", "Prim"),
    (r"\blukoil\b", "Lukoil"),
    (r"\baral\b", "Aral"),
    (r"\besso\b", "Esso"),
    (r"\bbp\b", "BP"),
    (r"\bavia\b", "Avia"),
    (r"\bjet\b", "JET"),
    (r"\bq8\b", "Q8"),
    (r"\btamoil\b", "Tamoil"),
    (r"\bslovnaft\b", "Slovnaft"),
    (r"\bturm[öo]l\b", "Turmöl"),
    (r"\bhruška\b", "Hruška"),
    (r"\btesla\b", "Tesla"),
    (r"\bionity\b", "Ionity"),
    (r"\bčez\b", "ČEZ"),
    (r"\bpre\b", "PRE"),
]
_BRAND_RES = [(re.compile(pattern, re.IGNORECASE), brand) for pattern, brand in _BRANDS]


def station_brand(name):
    """Značka podle názvu stanice; neznámá značka = první slovo názvu."""
    name = " ".join((name or "").split())
    if not name:
        return UNKNOWN
    for pattern, brand in _BRAND_RES:
        if pattern.search(name):
            return brand
    return name.split(" ")[0]


def _new_bucket():
    return {"count": 0, "cost": ZERO, "volume": defaultdict(lambda: ZERO), "priced_volume": ZERO,
            "priced_cost": ZERO, "last": None}


def _add(bucket, record):
    bucket["count"] += 1
    bucket["cost"] += record.price_local or ZERO
    bucket["volume"][record.unit] += record.volume_liters or ZERO
    if record.price_local is not None and record.volume_liters and record.unit == "l":
        bucket["priced_volume"] += record.volume_liters
        bucket["priced_cost"] += record.price_local
    if bucket["last"] is None or record.refuel_datetime > bucket["last"]:
        bucket["last"] = record.refuel_datetime


def _finish(bucket):
    bucket["volume"] = dict(sorted(bucket["volume"].items()))
    bucket["avg_price"] = (bucket["priced_cost"] / bucket["priced_volume"]) if bucket["priced_volume"] else None
    return bucket


def station_overview(records):
    """Seznam značek [{brand, count, cost, volume, avg_price, last, stations: [...]}],
    nejčastější nahoře. Stanice v rámci značky se rozlišují podle adresy (bez ní podle názvu)."""
    brands = defaultdict(lambda: {"total": _new_bucket(), "stations": {}})
    for record in records:
        brand = station_brand(record.station_name)
        address = " ".join((record.station_address or "").split())
        name = " ".join((record.station_name or "").split())
        key = (address or name).lower()
        group = brands[brand]
        station = group["stations"].get(key)
        if station is None:
            station = group["stations"][key] = {**_new_bucket(), "name": name, "address": address}
        _add(station, record)
        _add(group["total"], record)

    result = []
    for brand, group in brands.items():
        stations = sorted((_finish(s) for s in group["stations"].values()),
                          key=lambda s: (-s["count"], -s["cost"], s["address"] or s["name"]))
        result.append({"brand": brand, **_finish(group["total"]), "stations": stations})
    result.sort(key=lambda b: (b["brand"] == UNKNOWN, -b["count"], -b["cost"], b["brand"]))
    return result
