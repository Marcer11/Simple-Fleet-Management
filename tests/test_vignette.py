"""Ikona dálniční známky v přehledu vozidel."""
from datetime import date, timedelta

from models import Expense
from test_web import register, add_vehicle, app, db  # noqa: F401


def _vignette(db, vid, start, days):
    db.add(Expense(vehicle_id=vid, expense_date=start, category="Dálniční známka", price_paid=100,
                   currency_code="CZK", price_local=100, valid_from=start, valid_until=start + timedelta(days=days - 1)))
    db.commit()


def test_vignette_icon_in_vehicle_list(app, db):
    from services.vehicle_service import VehicleService
    from models import Vehicle
    client = register(app, "vig@example.com")
    today = date.today()
    valid = add_vehicle(client, model="Platna")
    soon = add_vehicle(client, model="Konci")
    old = add_vehicle(client, model="Stara")
    none = add_vehicle(client, model="Zadna")
    chained = add_vehicle(client, model="Navazuje")
    _vignette(db, valid, today - timedelta(days=10), 365)
    _vignette(db, soon, today - timedelta(days=5), 10)
    _vignette(db, old, today - timedelta(days=400), 365)
    _vignette(db, chained, today - timedelta(days=5), 10)
    _vignette(db, chained, today + timedelta(days=5), 30)  # navazující koupená dopředu

    status = VehicleService(db).vignette_status([db.get(Vehicle, i) for i in (valid, soon, old, none, chained)])
    assert status[valid] == ("valid", today + timedelta(days=354))
    assert status[soon][0] == "expiring"
    assert status[old][0] == "expired"
    assert none not in status
    assert status[chained] == ("valid", today + timedelta(days=34))

    html = client.get("/vehicles").text
    assert "<th>Známka</th>" in html
    assert "vignette-valid" in html and "vignette-expiring" in html and "vignette-expired" in html
    assert "Dálniční známka platí do" in html
