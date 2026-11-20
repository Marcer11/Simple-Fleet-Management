from datetime import date, timedelta

from fastapi.testclient import TestClient  # noqa: F401

from models import FuelRecord, FuelType
from models.fuel_record import guess_fuel_category
from services.stations import station_brand, station_overview
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401


def test_guess_category():
    assert guess_fuel_category("Natural 95") == "Benzín"
    assert guess_fuel_category("Verva 100") == "Benzín"
    assert guess_fuel_category("Verva Diesel") == "Nafta"
    assert guess_fuel_category("LPG") == "LPG"
    assert guess_fuel_category("Elektřina") == "Elektřina"
    assert guess_fuel_category("AdBlue") is None


def test_new_fuel_is_offered_and_consumption_by_category(app, db):
    client = register(app, "f@example.com")
    vid = add_vehicle(client)
    today = date.today()
    add_fuel(client, vid, today - timedelta(days=30), 10000, "40")
    # jiný název benzínu - spotřeba se počítá dál (stejný druh)
    r = add_fuel(client, vid, today - timedelta(days=10), 10500, "35", fuel_type="natural  95")
    assert r.status_code == 303, r.text
    record = db.query(FuelRecord).filter_by(odometer=10500).one()
    assert record.fuel_type == "natural 95" and record.fuel_category == "Benzín"
    assert float(record.consumption) == 7.0
    # nové palivo se nabízí
    assert '<option value="natural 95">' in client.get("/fuel-records/add").text
    # podruhé jiným písmem -> uložený tvar
    add_fuel(client, vid, today - timedelta(days=5), 10900, "30", fuel_type="NATURAL 95")
    assert db.query(FuelRecord).filter_by(odometer=10900).one().fuel_type == "natural 95"

    page = client.get("/fuel-types").text
    assert "natural 95" in page and "Elektřina" in page
    item = db.query(FuelType).filter_by(name="natural 95").one()
    # přejmenování se promítne do tankování
    r = post(client, f"/fuel-types/{item.id}/edit", {"name": "Natural 95", "category": "Benzín"})
    assert r.status_code == 303
    db.expire_all()
    assert {r.fuel_type for r in db.query(FuelRecord).filter(FuelRecord.odometer > 10000)} == {"Natural 95"}
    # vlastní řada spotřeby
    post(client, f"/fuel-types/{item.id}/edit", {"name": "Natural 95", "category": ""})
    db.expire_all()
    assert db.query(FuelRecord).filter_by(odometer=10500).one().consumption is None
    # duplicitní název
    r = post(client, "/fuel-types/add", {"name": "natural 95", "category": "Benzín"})
    assert r.status_code == 400 and "už v seznamu" in r.text
    assert post(client, "/fuel-types/add", {"name": "Verva Diesel", "category": "Nafta"}).status_code == 303
    # odebrání jen z nabídky
    post(client, f"/fuel-types/{item.id}/delete", {})
    assert '<option value="Natural 95">' not in client.get("/fuel-records/add").text
    assert db.query(FuelRecord).filter_by(fuel_type="Natural 95").count() == 2


def test_fuel_types_are_private(app, db):
    alice = register(app, "a@example.com")
    bob = register(app, "b@example.com")
    alice.get("/fuel-types")
    item = db.query(FuelType).first()
    assert post(bob, f"/fuel-types/{item.id}/delete", {}).status_code == 404


def test_station_overview(app):
    assert station_brand("Benzina ORLEN Praha") == "ORLEN"
    assert station_brand("MOL Štěrboholská spojka") == "MOL"
    assert station_brand("Pumpa U Lesa") == "Pumpa"
    assert station_brand("") == "Neuvedeno"

    client = register(app, "s@example.com")
    vid = add_vehicle(client)
    today = date.today()
    add_fuel(client, vid, today - timedelta(days=30), 10000, "40", station_name="MOL Praha",
             station_address="Štěrboholská 1, Praha")
    add_fuel(client, vid, today - timedelta(days=20), 10400, "40", station_name="MOL",
             station_address="Štěrboholská 1,  Praha")
    add_fuel(client, vid, today - timedelta(days=10), 10800, "20", unit_price="45", station_name="MOL Brno",
             station_address="Vídeňská 5, Brno")
    add_fuel(client, vid, today - timedelta(days=5), 11000, "10", station_name="Shell D1")
    page = client.get("/fuel-records/stations").text
    assert "Štěrboholská 1, Praha" in page and "Vídeňská 5, Brno" in page and "Shell" in page

    from sqlalchemy.orm import sessionmaker  # noqa: F401
    from web.deps import get_db
    db = next(app.dependency_overrides[get_db]())
    overview = station_overview(db.query(FuelRecord).all())
    mol = overview[0]
    assert mol["brand"] == "MOL" and mol["count"] == 3 and float(mol["cost"]) == 40 * 40 * 2 + 900
    assert [s["count"] for s in mol["stations"]] == [2, 1]
    assert float(mol["stations"][0]["avg_price"]) == 40
    assert overview[1]["brand"] == "Shell"
