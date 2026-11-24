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


def test_consumption_by_category_and_breakdown(app, db):
    client = register(app, "b@example.com")
    vid = add_vehicle(client)
    d0 = date.today() - timedelta(days=60)
    # Natural 95 -> Natural 98: spotřeba se počítá (obojí benzín)
    add_fuel(client, vid, d0, 10000, "40", fuel_type="Natural 95")
    add_fuel(client, vid, d0 + timedelta(days=10), 10500, "38", fuel_type="Natural 98")
    add_fuel(client, vid, d0 + timedelta(days=20), 11000, "37", fuel_type="Natural 95")
    # LPG ve stejnou dobu a při stejném stavu tachometru jako benzín - vlastní řada
    lpg_day = d0 + timedelta(days=20)
    r = add_fuel(client, vid, lpg_day, 11000, "40", fuel_type="LPG", unit_price="18")
    assert r.status_code == 303, r.text
    add_fuel(client, vid, d0 + timedelta(days=30), 12000, "50", fuel_type="LPG", unit_price="18")
    # AdBlue nesmí rozbít ani tvořit spotřebu benzínu
    add_fuel(client, vid, d0 + timedelta(days=31), 12000, "10", fuel_type="AdBlue", unit_price="20")
    add_fuel(client, vid, d0 + timedelta(days=40), 12500, "36", fuel_type="Natural 98")

    by_odo = {(r.odometer, r.fuel_type): r for r in db.query(FuelRecord).all()}
    assert float(by_odo[(10500, "Natural 98")].consumption) == 7.6
    assert float(by_odo[(11000, "Natural 95")].consumption) == 7.4
    assert float(by_odo[(12000, "LPG")].consumption) == 5.0
    assert by_odo[(12000, "AdBlue")].consumption is None
    assert float(by_odo[(12500, "Natural 98")].consumption) == 2.4  # 36 l / 1500 km

    from services.stats_service import StatsService
    groups = StatsService(db).fuel_breakdown(vid)
    assert [g["name"] for g in groups] == ["Benzín", "LPG", "AdBlue"]
    assert [g["role"] for g in groups] == ["hlavní", "alternativní", None]
    benzin = groups[0]
    assert float(benzin["volume"]) == 40 + 38 + 37 + 36 and benzin["count"] == 4
    assert round(float(benzin["consumption"]), 2) == round((38 + 37 + 36) / 2500 * 100, 2)
    names = {f["name"]: f for f in benzin["fuels"]}
    assert round(float(names["Natural 98"]["consumption"]), 2) == round((38 + 36) / 2000 * 100, 2)
    assert float(names["Natural 95"]["consumption"]) == 7.4

    page = client.get(f"/vehicles/{vid}").text
    assert "Spotřeba a palivo" in page and "alternativní" in page and "Natural 98" in page
    assert "Spotřeba a palivo" in client.get(f"/vehicles/{vid}/stats?period=all").text


def test_recalculate_command(app, db, monkeypatch, capsys):
    client = register(app, "r@example.com")
    vid = add_vehicle(client)
    d0 = date.today() - timedelta(days=20)
    add_fuel(client, vid, d0, 10000, "40")
    add_fuel(client, vid, d0 + timedelta(days=10), 10500, "35")
    record = db.query(FuelRecord).filter_by(odometer=10500).one()
    record.consumption = None  # zastaralá hodnota
    db.commit()

    import manage
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(manage, "SessionLocal", sessionmaker(bind=db.get_bind()))
    manage.main(["recalculate-consumption"])
    assert "změněno tankování: 1" in capsys.readouterr().out
    db.expire_all()
    assert float(db.query(FuelRecord).filter_by(odometer=10500).one().consumption) == 7.0


def test_fuel_type_multiple_brands_and_station_check(app, db):
    client = register(app, "evo@example.com")
    vid = add_vehicle(client)
    # víc pump zaškrtnutím + další dopsaná
    r = post(client, "/fuel-types/add", {"name": "EVO 100+", "category": "Benzín",
                                         "station_brand": ["MOL", "OMV"], "station_brands": "km-prona"})
    assert r.status_code == 303
    evo = db.query(FuelType).filter_by(name="EVO 100+").one()
    assert evo.brands == ["MOL", "OMV", "km-prona"]
    page = client.get("/fuel-types").text
    assert 'name="station_brand" value="MOL" checked' in page and 'name="station_brand" value="OMV" checked' in page
    # úprava: jen MOL
    r = post(client, f"/fuel-types/{evo.id}/edit", {"name": "EVO 100+", "category": "Benzín",
                                                    "station_brand": ["MOL"]})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(FuelType, evo.id).brands == ["MOL"]

    # tankování EVO 100+ na jiné pumpě nejde uložit
    r = add_fuel(client, vid, date.today(), 1000, "40", fuel_type="EVO 100+", station_name="KM-PRONA Praha")
    assert r.status_code == 400 and "jen pro pumpy MOL" in r.text
    assert add_fuel(client, vid, date.today(), 1000, "40", fuel_type="EVO 100+", station_name="MOL Brno").status_code == 303
    assert add_fuel(client, vid, date.today(), 1100, "40", fuel_type="EVO 100+").status_code == 303  # bez stanice
    record = db.query(FuelRecord).filter_by(station_name="MOL Brno").one()
    r = post(client, f"/fuel-records/{record.id}/edit", {
        "vehicle_id": vid, "refuel_date": date.today().isoformat(), "refuel_time": "12:00", "odometer": 1000,
        "fuel_type": "EVO 100+", "volume_liters": "40", "unit_price": "40", "currency_code": "CZK",
        "full_tank": "on", "station_name": "KM-PRONA"})
    assert r.status_code == 400 and "jen pro pumpy MOL" in r.text
