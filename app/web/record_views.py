"""Detail záznamu jen pro čtení (tankování, servis, výdaj, poznámka, půjčení, přezutí, kontrola dezénu, poškození).

Každá funkce vrací slovník pro šablonu record_detail.html: nadpis, řádky (popisek, hodnota), text poznámky
a adresy úpravy / smazání. Úprava a smazání jsou dole v části „Správa záznamu“, ne hned nahoře.
"""
from markupsafe import Markup

from models.tire import TIRE_PLACES
from services.places import place_url
from web.deps import fmt_czk, fmt_date, fmt_datetime, fmt_km, fmt_money, fmt_num, fmt_qty


def _when(day, at=None):
    return f"{fmt_date(day)} {at:%H:%M}" if at else fmt_date(day)


def _link(url, text):
    return Markup('<a href="{}">{}</a>').format(url, text) if url else text


def _place(kind, name, address=None):
    if not (name or address):
        return None
    link = _link(place_url(kind, name, address), name or address)
    if address and name:
        return Markup("{}<div class=\"small muted\">{}</div>").format(link, address)
    return link


def _price(price_local, price_paid=None, currency="CZK", decimals=2):
    if price_local is None and price_paid is None:
        return None
    text = fmt_czk(price_local, decimals) if price_local is not None else ""
    if currency and currency != "CZK" and price_paid is not None:
        return Markup("{} <span class=\"small muted\">({})</span>").format(text, fmt_money(price_paid, currency))
    return text


def _insurance(r):
    if not getattr(r, "insurance_claim", False):
        return []
    parts = [r.insurer, r.policy_number and f"pojistka {r.policy_number}",
             r.claim_number and f"pojistná událost {r.claim_number}"]
    rows = [("Pojišťovna", " · ".join(p for p in parts if p) or "ano")]
    if r.insurance_paid is not None:
        rows.append(("Uhradila pojišťovna", fmt_czk(r.insurance_paid, 0)))
        rows.append(("Zůstalo na mně", fmt_czk(r.own_cost, 0)))
    return rows


def _base(record, kind_label, icon, title, when, edit_url, delete_url, tab, delete_confirm="Opravdu smazat tento záznam?"):
    vehicle = record.vehicle
    return {"record": record, "kind_label": kind_label, "icon": icon, "title": title, "when": when,
            "vehicle": vehicle, "back_url": f"/vehicles/{vehicle.id}?tab={tab}" if vehicle else None,
            "edit_url": edit_url,
            "delete_url": delete_url, "delete_confirm": delete_confirm, "can_delete": True,
            "rows": [], "sections": [], "text": None, "text_label": "Poznámka"}


def fuel(r):
    view = _base(r, "Tankování", "fuel", r.fuel_type, fmt_datetime(r.refuel_datetime),
                 f"/fuel-records/{r.id}/edit", f"/fuel-records/{r.id}/delete", "fuel",
                 "Opravdu smazat toto tankování?")
    flags = ", ".join(x for x in ("plná nádrž" if r.full_tank else "částečné tankování",
                                  "předchozí tankování vynecháno" if r.skipped_refuel else "") if x)
    view["rows"] = [
        ("Tachometr", fmt_km(r.odometer)),
        ("Palivo", f"{r.fuel_type} · {flags}"),
        ("Množství", f"{fmt_qty(r.volume_liters)} {r.unit}"),
        ("Cena za jednotku", f"{fmt_num(r.unit_price_local, 2)} Kč/{r.unit}" if r.unit_price_local is not None else None),
        ("Cena", _price(r.price_local, r.price_paid, r.currency_code)),
        ("Spotřeba", f"{fmt_num(r.consumption, 2)} {r.unit}/100 km" if r.consumption else None),
        ("Platba", r.payment_method),
        ("Čerpací stanice", _place("station", r.station_name, r.station_address)),
        ("Zapsal", r.created_by.name if getattr(r, "created_by", None) else None),
    ]
    view["text"] = r.note
    return view


def service(r):
    view = _base(r, "Servis", "service", r.service_type, _when(r.service_date, r.service_time),
                 f"/services/{r.id}/edit", f"/services/{r.id}/delete", "service", "Opravdu smazat tento servis?")
    pickup = (_when(r.date_to, r.time_to) if r.date_to else ("zatím v servisu" if r.in_progress else None))
    km = None
    if r.odometer is not None:
        km = fmt_km(r.odometer) + (f" → {fmt_km(r.odometer_to)}" if r.odometer_to is not None else "")
    view["rows"] = [
        ("Předáno", _when(r.service_date, r.service_time)),
        ("Vyzvednuto", pickup),
        ("V servisu", r.duration),
        ("Tachometr", km),
        ("Servis najel", fmt_km(r.distance) if r.distance is not None else None),
        ("Servis (místo)", _place("service", r.place)),
        ("Cena", _price(r.price_local, r.price_paid, r.currency_code)),
        *_insurance(r),
    ]
    view["text"] = r.note
    return view


def expense(r):
    view = _base(r, "Výdaj", "expense", r.category, fmt_date(r.expense_date),
                 f"/expenses/{r.id}/edit", f"/expenses/{r.id}/delete", "expenses", "Opravdu smazat tento výdaj?")
    validity = None
    if r.valid_until:
        validity = f"{fmt_date(r.valid_from)} – {fmt_date(r.valid_until)}" if r.valid_from else f"do {fmt_date(r.valid_until)}"
    view["rows"] = [
        ("Datum", fmt_date(r.expense_date)),
        ("Popis", r.description),
        ("Místo", _place("expense", r.place)),
        ("Tachometr", fmt_km(r.odometer) if r.odometer is not None else None),
        ("Částka", _price(r.price_local, r.price_paid, r.currency_code)),
        ("Platnost", validity),
        *_insurance(r),
    ]
    view["text"] = r.note
    return view


def note(n):
    view = _base(n, "Poznámka", "note", n.title, fmt_datetime(n.note_datetime),
                 f"/notes/{n.id}/edit", f"/notes/{n.id}/delete", "notes", "Opravdu smazat tuto poznámku?")
    view["rows"] = [
        ("Kdy", fmt_datetime(n.note_datetime)),
        ("Typ", n.category),
        ("Tachometr", fmt_km(n.odometer) if n.odometer is not None else None),
        ("Zapsal", n.created_by.name if n.created_by else None),
    ]
    view["text"], view["text_label"] = n.text, "Text"
    return view


def rental(r):
    lender = r.vehicle.lender or r.provider
    view = _base(r, "Půjčení", "key", f"Půjčení – {lender}" if lender else "Půjčení",
                 _when(r.date_from, r.time_from), f"/rentals/{r.id}/edit", f"/rentals/{r.id}/delete", "detail",
                 "Opravdu smazat toto půjčení?")
    km = None
    if r.odometer_from is not None or r.odometer_to is not None:
        km = f"{fmt_km(r.odometer_from) or '?'} → {fmt_km(r.odometer_to) or '?'}"
    view["rows"] = [
        ("Půjčeno", _when(r.date_from, r.time_from)),
        ("Vráceno", _when(r.date_to, r.time_to) if r.date_to else "zatím nevráceno"),
        ("Dní", r.days),
        ("Tachometr", km),
        ("Najeto", fmt_km(r.distance) if r.distance is not None else None),
        ("Půjčovné", _price(r.price_local, r.price_paid, r.currency_code)),
    ]
    view["text"] = r.note
    return view


def _tire(tire):
    """Ikona typu + název pneumatiky s odkazem (bez slova letní / zimní)."""
    from web.deps import templates
    icon = templates.env.get_template("_macros.html").module.season_icon(tire.season)
    return Markup('{} <a href="/tires/{}">{}</a>').format(Markup(icon), tire.id, tire.name)


def _tire_line(mount, extra=""):
    return Markup('{} <span class="small muted">{}{}</span>').format(
        _tire(mount.tire), mount.position_label.lower(), extra)


def tire_swap(s, can_delete=True):
    title = "Vyřazení pneumatik" if s.is_retirement else "Přezutí pneumatik"
    view = _base(s, title, "tire", title, fmt_date(s.swap_date),
                 f"/tire-swaps/{s.id}/edit", f"/tire-swaps/{s.id}/delete", "tires",
                 "Zrušit vyřazení? Kola se vrátí na vozidlo." if s.is_retirement
                 else "Smazat přezutí? Pneumatiky se vrátí, jak byly před ním.")
    view["can_delete"] = can_delete
    if s.is_retirement:
        view["edit_url"] = None
        view["rows"] = [("Datum", fmt_date(s.swap_date)), ("Tachometr", fmt_km(s.odometer))]
        view["sections"] = [("Vyřazeno", [
            Markup("{} <span class=\"small muted\">{}{}</span>").format(
                _tire(r.tire), r.wheels_label or r.quantity_label, f" – {r.reason}" if r.reason else "")
            for r in s.retirements] or ["nic"]),
            ("Zůstává na voze", [_tire_line(m) for m in s.mounted] or ["nic"])]
        view["text"] = s.note
        return view
    service_record = s.service_record
    where = TIRE_PLACES.get(s.place, s.place)
    if service_record and service_record.place:
        where = Markup("{} · {}").format(where, _place("service", service_record.place))
    view["rows"] = [
        ("Datum", fmt_date(s.swap_date)),
        ("Tachometr", fmt_km(s.odometer)),
        ("Kde", where),
        ("Cena", _price(service_record.price_local, service_record.price_paid, service_record.currency_code)
         if service_record else None),
    ]
    stayed = {m.tire_id for m in s.removed}
    mounted = [_tire_line(m, " (zůstává)" if m.tire_id in stayed else "") for m in s.mounted]
    removed = [_tire_line(m, f" · dezén {m.treads_label} mm" if m.treads_label else "")
               for m in s.removed if m.vehicle_id == s.vehicle_id]
    view["sections"] = [("Nasazeno", mounted or ["jen sundáno"]), ("Sundáno", removed or ["nic"])]
    view["text"] = s.note
    return view


def tire_check(c):
    view = _base(c, "Kontrola dezénu", "gauge", "Kontrola dezénu", fmt_date(c.check_date),
                 f"/tire-checks/{c.id}/edit", f"/tire-checks/{c.id}/delete", "tires", "Smazat kontrolu dezénu?")
    view["rows"] = [("Datum", fmt_date(c.check_date)), ("Tachometr", fmt_km(c.odometer)),
                    ("Zapsal", c.created_by.name if c.created_by else None)]
    view["sections"] = [("Naměřeno (mm)", [
        Markup('{}: {}').format(_tire(tire), " · ".join(r.text for r in readings))
        for tire, readings in c.by_tire()])]
    view["text"] = c.note
    return view


def tire_defect(d):
    view = _base(d, "Poškození pneumatiky", "warning", d.description, fmt_date(d.defect_date),
                 f"/tire-defects/{d.id}/edit", f"/tire-defects/{d.id}/delete", "tires",
                 "Smazat záznam o poškození?")
    view["rows"] = [
        ("Pneumatika", _tire(d.tire)),
        ("Datum", fmt_date(d.defect_date)),
        ("Tachometr", fmt_km(d.odometer) if d.odometer is not None else None),
        ("Pozice", d.position),
        ("Oprava", _price(d.expense.price_local, d.expense.price_paid, d.expense.currency_code) if d.expense else None),
    ]
    if d.vehicle is None:  # poškození bez vozidla: zpět na pneumatiku
        view["back_url"] = f"/tires/{d.tire_id}"
    return view

