"""Stav tachometru se kontroluje proti všem záznamům vozidla, ne jen proti stejnému druhu záznamu."""
from datetime import date

from models import TireSwap
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401


def test_fuel_checked_against_other_records(app, db):
    client = register(app, "odo@example.com")
    vid = add_vehicle(client)
    # poznámka se stavem 20 000 km 10. 3.
    assert post(client, "/notes/add", {"vehicle_id": vid, "note_date": "2026-03-10", "note_time": "12:00",
                                       "odometer": "20000", "category": "Garáž"}).status_code == 303
    # servis 20. 3. s 21 000 km, vyzvednutí 22. 3. s 21 050 km
    assert post(client, "/services/add", {"vehicle_id": vid, "st:Brzdy": "on", "currency_code": "CZK",
                                          "service_date": "2026-03-20", "odometer": "21000",
                                          "date_to": "2026-03-22", "odometer_to": "21050"}).status_code == 303

    # tankování před poznámkou s vyšším stavem -> chyba
    r = add_fuel(client, vid, date(2026, 3, 5), 20500, "40")
    assert r.status_code == 400 and "vyšší než u poznámky" in r.text
    # tankování mezi předáním a vyzvednutím mimo rozsah -> chyba
    r = add_fuel(client, vid, date(2026, 3, 25), 21010, "40")
    assert r.status_code == 400 and "nižší než u vyzvednutí ze servisu" in r.text
    r = add_fuel(client, vid, date(2026, 3, 15), 21500, "40")
    assert r.status_code == 400 and "vyšší než u servisu" in r.text
    # správné pořadí projde, stejný den bez času se neporovnává
    assert add_fuel(client, vid, date(2026, 3, 15), 20500, "40").status_code == 303
    assert add_fuel(client, vid, date(2026, 3, 20), 20990, "40").status_code == 303

    # výdaj a servis se také kontrolují
    r = post(client, "/expenses/add", {"vehicle_id": vid, "expense_date": "2026-03-01", "category": "Mytí",
                                       "price_paid": "200", "currency_code": "CZK", "odometer": "25000"})
    assert r.status_code == 400 and "vyšší než u" in r.text
    r = post(client, "/services/add", {"vehicle_id": vid, "st:Olej": "on", "currency_code": "CZK",
                                       "service_date": "2026-04-01", "odometer": "15000"})
    assert r.status_code == 400 and "nižší než u" in r.text


def test_fuel_before_tire_swap_with_higher_km_rejected(app, db):
    """Nahlášený případ: tankování před přezutím s vyšším stavem než přezutí."""
    client = register(app, "odoswap@example.com")
    vid = add_vehicle(client)
    db.add(TireSwap(vehicle_id=vid, swap_date=date(2026, 4, 10), odometer=30000, place="home"))
    db.commit()
    assert db.query(TireSwap).count() == 1
    r = add_fuel(client, vid, date(2026, 4, 5), 30500, "40")
    assert r.status_code == 400 and "vyšší než u přezutí 10.04.2026" in r.text
    assert add_fuel(client, vid, date(2026, 4, 5), 29800, "40").status_code == 303
    # i úprava existujícího tankování
    from models import FuelRecord
    record = db.query(FuelRecord).one()
    r = post(client, f"/fuel-records/{record.id}/edit", {
        "vehicle_id": vid, "refuel_date": "2026-04-05", "refuel_time": "12:00", "odometer": "30100",
        "fuel_type": "Benzín", "volume_liters": "40", "unit_price": "40", "currency_code": "CZK", "full_tank": "on"})
    assert r.status_code == 400 and "přezutí" in r.text
