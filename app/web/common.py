"""Pomocné funkce sdílené routery."""
import csv
import io
from datetime import date

from fastapi.responses import Response

from models.vehicle import ROLE_EDITOR, ROLE_VIEWER
from services.errors import NotFoundError
from services.maintenance_service import collect_alerts
from services.vehicle_service import VehicleService
from web.deps import flash

COMMON_CURRENCIES = ["CZK", "EUR", "PLN", "HUF", "CHF", "USD", "GBP", "RON", "BGN", "DKK", "SEK", "NOK"]


def editable_vehicles(db, user):
    """Vozidla, do kterých může uživatel zapisovat (vlastní + sdílená s právem úprav)."""
    service = VehicleService(db)
    ids = set(service.get_accessible_ids(user, ROLE_EDITOR))
    return [v for v in service.get_vehicles_for_user(user) if v.id in ids]


def visible_vehicles(db, user):
    return VehicleService(db).get_vehicles_for_user(user)


def check_record_access(db, user, record, min_role=ROLE_VIEWER):
    """Ověří přístup k záznamu přes jeho vozidlo; neexistující záznam = 404."""
    if record is None:
        raise NotFoundError("Záznam nenalezen.")
    return VehicleService(db).get_vehicle_for_user(record.vehicle_id, user, min_role)


def render_record(request, db, user, record, view):
    """Detail záznamu jen pro čtení (web/record_views.py); úprava jen pro editory vozidla."""
    from models.vehicle import ROLE_LEVELS
    from web.deps import render
    vehicle = check_record_access(db, user, record)
    role = VehicleService(db).get_role(vehicle, user)
    return render(request, "record_detail.html", view=view,
                  can_edit=ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS[ROLE_EDITOR])


def flash_vehicle_alerts(request, db, vehicle):
    """Po uložení záznamu upozorní na blížící se servis a upomínky (zadání z readme)."""
    for alert in collect_alerts(db, [vehicle])[:5]:
        category = "danger" if alert.status.level == "overdue" else "warning"
        flash(request, f"{vehicle.short_name}: {alert.title} – {alert.status.summary}", category)


def default_filter_period(date_from, date_to):
    """Výchozí filtr seznamů: posledních 12 měsíců."""
    if date_from is None and date_to is None:
        today = date.today()
        try:
            return today.replace(year=today.year - 1), None
        except ValueError:  # 29. února
            return today.replace(year=today.year - 1, day=28), None
    return date_from, date_to


def csv_response(filename, header, rows):
    buffer = io.StringIO()
    buffer.write("﻿")  # BOM - Excel pak správně zobrazí češtinu
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if v is None else (v.strftime("%d.%m.%Y") if isinstance(v, date) else v) for v in row])
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def decimal_csv(value):
    return "" if value is None else str(value).replace(".", ",")
