from datetime import date, datetime, timedelta

from models import FuelType, Vehicle, VehicleNote
from services.fuel_type_service import FuelTypeService
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401


def test_notes_and_timeline(app, db):
    client = register(app, "t@example.com", "Martin")
    vid = add_vehicle(client, purchase_date="2024-03-01", purchase_price="250000")
    today = date.today()
    add_fuel(client, vid, today - timedelta(days=10), 10000, "40", station_name="MOL Praha")
    post(client, "/services/add", {"vehicle_id": vid, "service_date": (today - timedelta(days=5)).isoformat(),
                                   "odometer": 10100, "service_type": "Výměna oleje", "price_paid": "2500",
                                   "currency_code": "CZK"})
    r = post(client, "/notes/add", {"vehicle_id": vid, "note_date": (today - timedelta(days=2)).isoformat(),
                                    "note_time": "18:30", "odometer": 10250, "category": "Garáž",
                                    "text": "Uloženo do garáže u rodičů"})
    assert r.status_code == 303, r.text
    note = db.query(VehicleNote).one()
    assert note.note_datetime == datetime.combine(today - timedelta(days=2), datetime.min.time()).replace(hour=18, minute=30)
    assert note.created_by.name == "Martin"
    # poznámka bez typu i textu nejde
    r = post(client, "/notes/add", {"vehicle_id": vid, "note_date": today.isoformat()})
    assert r.status_code == 400 and "typ nebo text" in r.text

    page = client.get("/timeline?all=1").text
    for text in ("Garáž", "Uloženo do garáže", "Výměna oleje", "Benzín", "Nákup vozidla", "18:30"):
        assert text in page, text
    # pořadí: nejnovější nahoře
    assert page.index("Garáž") < page.index("Výměna oleje") < page.index("Nákup vozidla")
    only_notes = client.get("/timeline?all=1&kind=note").text
    assert "Garáž" in only_notes and "Výměna oleje" not in only_notes
    detail = client.get(f"/vehicles/{vid}").text
    assert "Časová osa" in detail and "Uloženo do garáže" in detail and "250 000 Kč" in detail
    # tachometr z poznámky je aktuální stav
    assert "10 250 km" in detail

    # úprava a smazání
    r = post(client, f"/notes/{note.id}/edit", {"vehicle_id": vid, "note_date": today.isoformat(),
                                                 "note_time": "08:00", "category": "Půjčeno", "text": ""})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(VehicleNote, note.id).category == "Půjčeno"

    other = register(app, "x@example.com")
    assert other.get(f"/notes/{note.id}/edit").status_code in (403, 404)
    assert "Půjčeno" not in other.get("/timeline?all=1").text
    post(client, f"/notes/{note.id}/delete", {})
    assert db.query(VehicleNote).count() == 0


def test_vehicle_prices_and_hidden_delete(app, db):
    client = register(app, "p@example.com")
    vid = add_vehicle(client)
    r = post(client, f"/vehicles/{vid}/edit", {"brand": "Škoda", "model": "Octavia", "purchase_date": "2020-01-10",
                                               "purchase_price": "300 000", "sale_date": "2026-11-01",
                                               "sale_price": "120000,50"})
    assert r.status_code == 303, r.text
    vehicle = db.get(Vehicle, vid)
    db.refresh(vehicle)
    assert float(vehicle.purchase_price) == 300000 and float(vehicle.sale_price) == 120000.5
    detail = client.get(f"/vehicles/{vid}").text
    assert "Ztráta hodnoty" in detail and "179 999,50" not in detail  # zaokrouhleno na Kč
    # smazání není v detailu, jen schované ve formuláři úprav
    assert f"/vehicles/{vid}/delete" not in detail
    edit = client.get(f"/vehicles/{vid}/edit").text
    assert f"/vehicles/{vid}/delete" in edit and "danger-zone" in edit
    timeline = client.get("/timeline?all=1").text
    assert "Prodej vozidla" in timeline and "Nákup vozidla" in timeline
    bad = post(client, f"/vehicles/{vid}/edit", {"brand": "Škoda", "model": "Octavia", "purchase_price": "-5"})
    assert bad.status_code == 400


def test_fuel_station_brands(app, db):
    client = register(app, "b@example.com")
    add_vehicle(client)
    r = post(client, "/fuel-types/add", {"name": "Verva 100", "category": "Benzín",
                                         "station_brands": "orlen, Benzina;  ORLEN"})
    assert r.status_code == 303, r.text
    verva = db.query(FuelType).filter_by(name="Verva 100").one()
    assert verva.station_brands == "ORLEN" and verva.brands == ["ORLEN"]
    post(client, f"/fuel-types/{verva.id}/edit", {"name": "Verva 100", "category": "Benzín",
                                                   "station_brands": "ORLEN, Shell"})
    db.expire_all()
    assert db.get(FuelType, verva.id).brands == ["ORLEN", "Shell"]
    assert FuelTypeService.clean_brands("") is None
    page = client.get("/fuel-records/add").text
    assert '"brands": ["ORLEN", "Shell"]' in page and '"name": "Verva 100"' in page
    assert 'list="brand-list"' in client.get("/fuel-types").text


def test_note_odometer_order(app, db):
    client = register(app, "m@example.com")
    vid = add_vehicle(client, brand="Honda", model="CBF")
    today = date.today()
    add_fuel(client, vid, today - timedelta(days=200), 14000, "12")

    def note(days_ago, km, category="Garáž"):
        return post(client, "/notes/add", {"vehicle_id": vid, "note_date": (today - timedelta(days=days_ago)).isoformat(),
                                           "note_time": "10:00", "odometer": km, "category": category})

    # podzim do garáže, jaro ven - stejný stav tachometru v různé dny je v pořádku
    assert note(150, 14200).status_code == 303
    assert note(20, 14200, "Vyndáno z garáže").status_code == 303
    # nižší stav než dřívější tankování / poznámka -> chyba
    r = note(100, 13900)
    assert r.status_code == 400 and "nižší než u tankování" in r.text
    r = note(10, 14100)
    assert r.status_code == 400 and "nižší než u poznámky" in r.text
    # vyšší než pozdější záznam -> chyba
    r = note(160, 14300)
    assert r.status_code == 400 and "vyšší než u poznámky" in r.text
    # bez tachometru se nekontroluje
    assert post(client, "/notes/add", {"vehicle_id": vid, "note_date": today.isoformat(),
                                       "category": "Půjčeno"}).status_code == 303
    # úprava poznámky se neporovnává sama se sebou
    first = db.query(VehicleNote).filter_by(category="Garáž").one()
    r = post(client, f"/notes/{first.id}/edit", {"vehicle_id": vid, "note_date": first.note_datetime.date().isoformat(),
                                                 "note_time": "11:00", "odometer": 14200, "category": "Garáž"})
    assert r.status_code == 303, r.text
