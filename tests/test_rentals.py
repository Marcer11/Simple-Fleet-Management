"""Půjčená vozidla: opakovaná půjčení, náklady ve statistikách a přehledech, graf kilometrů."""
from datetime import date

from models import Vehicle, VehicleRental
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401


def rental(client, vid, **data):
    payload = {"vehicle_id": vid, "provider": "Půjčovna AutoPraha", "date_from": "2026-05-01",
               "date_to": "2026-05-04", "odometer_from": "15000", "odometer_to": "15800",
               "price_paid": "3600", "currency_code": "CZK", **data}
    return post(client, "/rentals/add", payload)


def test_rental_vehicle_with_repeated_rentals(app, db):
    from services.stats_service import StatsService
    client = register(app, "rent@example.com")
    r = post(client, "/vehicles/add", {"brand": "Toyota", "model": "Yaris", "is_rental": "on"})
    assert r.status_code == 303 and r.headers["location"].startswith("/rentals/add?vehicle_id=")
    vid = int(r.headers["location"].rsplit("=", 1)[1])
    assert db.get(Vehicle, vid).is_rental is True
    own = add_vehicle(client, model="Octavia")
    # formulář půjčení nabízí jen půjčená vozidla
    form = client.get("/rentals/add").text
    assert "Toyota Yaris</option>" in form and "Škoda Octavia</option>" not in form

    assert rental(client, vid).status_code == 303
    # stejné auto podruhé, od známého, v eurech
    assert rental(client, vid, provider="Petr", date_from="2026-08-10", date_to="2026-08-12",
                  odometer_from="15800", odometer_to="16100", price_paid="40", currency_code="EUR").status_code == 303
    rentals = db.query(VehicleRental).order_by(VehicleRental.date_from).all()
    assert [x.provider for x in rentals] == ["Půjčovna AutoPraha", "Petr"]
    assert rentals[0].distance == 800 and rentals[1].price_local == 1000  # 40 EUR * 25
    # kontroly
    r = rental(client, vid, date_from="2026-09-10", date_to="2026-09-01")
    assert r.status_code == 400 and "před jeho začátkem" in r.text
    r = rental(client, vid, odometer_from="2000", odometer_to="1000")
    assert r.status_code == 400 and "menší než" in r.text
    r = rental(client, own)
    assert r.status_code == 400 and "není označené jako půjčené" in r.text

    # palivo půjčeného auta ve statistikách a grafu cen
    add_fuel(client, vid, date(2026, 5, 3), 15500, "30")
    stats = StatsService(db)
    summary = stats.vehicle_summary(vid, date(2026, 1, 1), date(2026, 12, 31))
    assert summary["rental_cost"] == 4600 and summary["total_cost"] == 4600 + 1200
    assert summary["distance"] == 1100
    fleet = stats.fleet_summary([db.get(Vehicle, vid), db.get(Vehicle, own)], date(2026, 1, 1), date(2026, 12, 31))
    assert fleet["rental_cost"] == 4600 and fleet["fuel_count"] == 1
    assert sum(fleet["charts"]["monthly_rental"]) == 4600
    assert fleet["charts"]["odometer_rental"] == ["Toyota Yaris"]
    assert "Benzín" in fleet["charts"]["unit_price"]
    assert stats.year_costs([vid], 2026)[vid] == 5800

    # stránky
    detail = client.get(f"/vehicles/{vid}").text
    assert "Půjčovna AutoPraha" in detail and "/rentals/add?vehicle_id=" in detail and "Půjčené" in detail
    page = client.get("/stats?period=2026").text
    assert "Půjčovné" in page and 'data-chart-optional="chart-odometer"' in page
    assert "Půjčení – Petr" in client.get("/?all=1").text
    assert "Půjčené" in client.get("/vehicles").text


def test_rental_zero_km_and_vehicle_form(app, db):
    client = register(app, "rent0@example.com")
    r = post(client, "/vehicles/add", {"brand": "Toyota", "model": "Yaris", "is_rental": "on"})
    vid = int(r.headers["location"].rsplit("=", 1)[1])
    assert rental(client, vid, odometer_from="0", odometer_to="", price_paid="").status_code == 303
    r = db.query(VehicleRental).one()
    assert r.odometer_from == 0 and r.odometer_to is None and r.distance is None and r.price_local is None
    form = client.get(f"/vehicles/{vid}/edit").text
    assert 'id="ownership-fields" data-hide-when="f-is_rental"' in form
    assert 'name="is_rental" value="on" checked' in form
