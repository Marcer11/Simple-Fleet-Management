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


def test_returned_rental_is_inactive_and_two_timeline_events(app, db):
    from datetime import timedelta
    from services.events import collect_events
    client = register(app, "ret@example.com")
    r = post(client, "/vehicles/add", {"brand": "Toyota", "model": "Yaris", "is_rental": "on"})
    vid = int(r.headers["location"].rsplit("=", 1)[1])
    today = date.today()
    # běžící půjčení (vrácení až zítra) -> aktivní
    rental(client, vid, date_from=(today - timedelta(days=3)).isoformat(),
           date_to=(today + timedelta(days=1)).isoformat(), odometer_to="")
    db.expire_all()
    assert db.get(Vehicle, vid).in_use and "Yaris" in client.get("/vehicles?show=active").text
    # vráceno -> neaktivní
    item = db.query(VehicleRental).one()
    post(client, f"/rentals/{item.id}/edit", {"vehicle_id": vid, "provider": "Půjčovna AutoPraha",
                                              "date_from": (today - timedelta(days=3)).isoformat(),
                                              "date_to": today.isoformat(), "odometer_from": "15000",
                                              "odometer_to": "15420", "price_paid": "3600", "currency_code": "CZK"})
    db.expire_all()
    vehicle = db.get(Vehicle, vid)
    assert vehicle.is_returned and not vehicle.in_use
    assert "Yaris" not in client.get("/vehicles?show=active").text
    assert "Vráceno" in client.get("/vehicles").text and "Vráceno" in client.get(f"/vehicles/{vid}").text
    # nové půjčení vozidlo znovu aktivuje
    rental(client, vid, date_from=(today + timedelta(days=10)).isoformat(), date_to="", odometer_from="15420",
           odometer_to="")
    db.expire_all()
    assert db.get(Vehicle, vid).in_use

    events = [e for e in collect_events(db, [db.get(Vehicle, vid)], kinds=["rental"])]
    titles = [(e.title, e.when.date(), e.odometer) for e in events]
    assert ("Vrácení – Půjčovna AutoPraha", today, 15420) in titles
    assert ("Půjčení – Půjčovna AutoPraha", today - timedelta(days=3), 15000) in titles
    back = next(e for e in events if e.title.startswith("Vrácení"))
    assert "najeto 420 km" in back.detail and back.amount is None and back.icon == "return"


def test_vehicle_list_sorted_by_last_record(app, db):
    client = register(app, "order@example.com")
    old = add_vehicle(client, model="Stará")
    new = add_vehicle(client, model="Nová")
    none = add_vehicle(client, model="Bez záznamu")
    add_fuel(client, old, date(2025, 3, 1), 1000, "40")
    add_fuel(client, new, date(2026, 2, 1), 1000, "40")
    post(client, "/notes/add", {"vehicle_id": old, "note_date": "2026-03-05", "note_time": "10:00", "text": "garáž"})
    page = client.get("/vehicles").text
    assert page.index("Škoda Stará") < page.index("Škoda Nová") < page.index("Škoda Bez záznamu")
    assert "5. 3. 2026" in page and "Poslední záznam" in page


def test_insurance_claim_on_service_and_expense(app, db):
    from models import Expense, ServiceRecord
    from services.stats_service import StatsService
    client = register(app, "ins@example.com")
    car = add_vehicle(client)
    form = client.get(f"/services/add?vehicle_id={car}").text
    assert 'id="f-insurance_claim"' in form and 'data-show-when="f-insurance_claim"' in form
    r = post(client, "/services/add", {"vehicle_id": car, "service_date": "2026-04-01", "st:Karoserie": "on",
                                       "price_paid": "20000", "currency_code": "CZK", "insurance_claim": "on",
                                       "insurer": "Kooperativa", "policy_number": "123456", "claim_number": "PU-7",
                                       "insurance_paid": "15000"})
    assert r.status_code == 303, r.text
    record = db.query(ServiceRecord).one()
    assert record.insurance_claim and record.insurer == "Kooperativa" and record.own_cost == 5000
    # plnění vyšší než cena nejde
    r = post(client, "/expenses/add", {"vehicle_id": car, "expense_date": "2026-04-02", "category": "Ostatní",
                                       "price_paid": "1000", "currency_code": "CZK", "insurance_claim": "on",
                                       "insurance_paid": "2000"})
    assert r.status_code == 400 and "vyšší než cena" in r.text
    # bez zaškrtnutí se údaje o pojistce neuloží
    post(client, "/expenses/add", {"vehicle_id": car, "expense_date": "2026-04-02", "category": "Ostatní",
                                   "price_paid": "1000", "currency_code": "CZK", "insurer": "Allianz",
                                   "insurance_paid": "500"})
    expense = db.query(Expense).one()
    assert not expense.insurance_claim and expense.insurer is None and expense.own_cost == 1000

    summary = StatsService(db).vehicle_summary(car, date(2026, 1, 1), date(2026, 12, 31))
    assert summary["service_cost"] == 5000 and summary["total_cost"] == 6000
    assert StatsService(db).year_costs([car], 2026)[car] == 6000
    page = client.get("/services?all=1").text
    assert "pojišťovna −15 000 Kč" in page
    assert "pojišťovna uhradila 15 000 Kč (Kooperativa)" in client.get("/?all=1").text
    edit_form = client.get(f"/services/{record.id}/edit").text
    assert 'name="insurance_claim" value="on" checked' in edit_form and 'value="PU-7"' in edit_form
