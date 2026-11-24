"""Návrat na seznam po úpravě záznamu (?next=), včetně filtru a řazení."""
from datetime import date, timedelta
from urllib.parse import quote

from models import FuelRecord
from test_web import register, post, add_vehicle, add_fuel, csrf, app, db  # noqa: F401

LIST = "/fuel-records?vehicle_id=1&fuel_type=Benz%C3%ADn&all=1&sort=0.2.d"


def fuel_payload(vid, **extra):
    return {"vehicle_id": vid, "refuel_date": (date.today() - timedelta(days=1)).isoformat(), "refuel_time": "12:00",
            "odometer": 1000, "fuel_type": "Benzín", "volume_liters": "40", "unit_price": "40",
            "currency_code": "CZK", "full_tank": "on", **extra}


def test_edit_returns_to_filtered_list(app, db):
    client = register(app, "nav@example.com")
    vid = add_vehicle(client)
    add_fuel(client, vid, date.today() - timedelta(days=1), 1000, "40")
    record = db.query(FuelRecord).one()
    next_q = quote(LIST, safe="")
    # uložení úpravy -> zpět na seznam se stejným filtrem a řazením
    r = post(client, f"/fuel-records/{record.id}/edit?next={next_q}", fuel_payload(vid, volume_liters="41"))
    assert r.status_code == 303 and r.headers["location"] == LIST
    # bez next jako dosud detail vozidla
    r = post(client, f"/fuel-records/{record.id}/edit", fuel_payload(vid, volume_liters="42"))
    assert r.headers["location"] == f"/vehicles/{vid}"
    # chyba ve formuláři -> formulář znovu (next zůstává v adrese)
    r = post(client, f"/fuel-records/{record.id}/edit?next={next_q}", fuel_payload(vid, volume_liters=""))
    assert r.status_code == 400
    # "uložit a přidat další" -> další formulář si návrat ponese dál
    r = post(client, f"/fuel-records/add?next={next_q}", fuel_payload(vid, odometer=1500, next="add",
                                                                    refuel_time="13:00"))
    assert r.status_code == 303 and r.headers["location"] == f"/fuel-records/add?vehicle_id={vid}&next={next_q}"
    # smazání -> zpět na seznam
    r = post(client, f"/fuel-records/{record.id}/delete?next={next_q}", {})
    assert r.status_code == 303 and r.headers["location"] == LIST


def test_next_must_be_local(app, db):
    client = register(app, "nav2@example.com")
    vid = add_vehicle(client)
    for bad in ("https://evil.example/x", "//evil.example/x", "/\evil.example"):
        r = post(client, f"/notes/add?next={quote(bad, safe='')}",
                 {"vehicle_id": vid, "note_date": date.today().isoformat(), "note_time": "10:00", "text": "x"})
        assert r.status_code == 303 and r.headers["location"] == f"/vehicles/{vid}"


def test_crud_and_vehicle_edit_return(app, db):
    client = register(app, "nav3@example.com")
    vid = add_vehicle(client)
    r = post(client, "/services/add?next=%2Fservices%3Fall%3D1", {"vehicle_id": vid, "service_date": "2026-01-05",
                                                                  "st:Brzdy": "on", "currency_code": "CZK"})
    assert r.headers["location"] == "/services?all=1"
    r = post(client, f"/vehicles/{vid}/edit?next=%2Fvehicles%3Fsort%3D0.3.d", {"brand": "Škoda", "model": "Fabia"})
    assert r.headers["location"] == "/vehicles?sort=0.3.d"
