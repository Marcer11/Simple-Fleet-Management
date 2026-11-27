import re
from datetime import date

from fastapi.testclient import TestClient

from models import User
from services import fleet_api
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401


def new_key(client):
    r = post(client, "/profile", {"action": "api_key_generate"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    return re.search(r'value="(fk_[^"]+)"', r.text).group(1)


def api(app, api_key, **params):
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return TestClient(app).get("/api/refuels", params=params, headers=headers)


def test_api_key_lifecycle(app, db):
    client = register(app, "a@example.com", "Alice")
    key = new_key(client)
    assert fleet_api.KEY_RE.match(key)
    user = db.query(User).filter_by(email="a@example.com").one()
    # v databázi je jen hash, klíč se znovu nezobrazí
    assert user.api_key_hash == fleet_api.hash_key(key) and key not in user.api_key_hash
    assert key not in client.get("/profile").text
    add_vehicle(client, license_plate="1AB 2345")
    params = {"plate": "1ab2345", "from": "2026-01-01T00:00:00", "to": "2026-01-02T00:00:00"}
    assert api(app, key, **params).status_code == 200

    # nový klíč zneplatní starý
    key2 = new_key(client)
    assert api(app, key, **params).status_code == 401
    assert api(app, key2, **params).status_code == 200

    post(client, "/profile", {"action": "api_key_revoke"})
    r = api(app, key2, **params)
    assert r.status_code == 401 and r.json() == {"error": "chybí nebo neplatný API klíč"}
    assert api(app, None, **params).status_code == 401
    # klíč nikdy v URL
    assert api(app, None, key=key2, **params).status_code == 401


def test_api_refuels(app):
    alice = register(app, "a@example.com", "Alice")
    bob = register(app, "b@example.com", "Bob")
    vid = add_vehicle(alice, license_plate="1AB 2345")
    post(alice, f"/vehicles/{vid}/sharing", {"email": "b@example.com", "role": "editor"})
    other = add_vehicle(alice, license_plate="9Z9 9999")

    add_fuel(alice, vid, date(2026, 7, 1), 10000, "40")                       # do plna před rozsahem
    add_fuel(alice, vid, date(2026, 7, 5), 10200, "10", full_tank="")          # částečné před rozsahem
    add_fuel(bob, vid, date(2026, 7, 12), 10600, "42.1", currency_code="EUR",  # v rozsahu (Bob)
             unit_price="", price_paid="60", station_name="OMV Wien Süd", station_address="Triester Str. 1")
    add_fuel(alice, vid, date(2026, 7, 18), 11000, "15", full_tank="")         # částečné po rozsahu
    add_fuel(alice, vid, date(2026, 7, 20), 11300, "30")                       # do plna po rozsahu
    add_fuel(alice, vid, date(2026, 7, 25), 11600, "30")                       # mimo
    add_fuel(alice, other, date(2026, 7, 12), 500, "20")                      # jiné vozidlo

    key = new_key(bob)
    base = {"plate": "1ab2345", "from": "2026-07-10T06:00:00", "to": "2026-07-15T20:00:00"}

    r = api(app, key, **base)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["vehicle"] == {"plate": "1AB2345", "name": "Škoda Octavia"}
    assert len(data["refuels"]) == 1
    item = data["refuels"][0]
    assert item["time"] == "2026-07-12T12:00:00" and item["odometer"] == 10600
    assert item["quantity"] == 42.1 and item["unit"] == "l" and item["full"] is True
    assert item["price_total"] == 60 and item["currency"] == "EUR" and item["price_czk"] == 1500
    assert item["station_name"] == "OMV Wien Süd" and item["station_address"] == "Triester Str. 1"
    assert item["fueled_by"] == "Bob" and item["id"].isdigit()

    # context=full: od posledního do plna před from po první do plna po to (všechna tankování, kdokoli)
    full = api(app, key, **base, context="full").json()["refuels"]
    assert [x["odometer"] for x in full] == [10000, 10200, 10600, 11000, 11300]
    assert [x["full"] for x in full] == [True, False, True, False, True]
    assert full[0]["fueled_by"] == "Alice"
    times = [x["time"] for x in full]
    assert times == sorted(times)

    # bez tankování do plna na kraji se rozsah nerozšiřuje
    late = api(app, key, plate="1AB2345", **{"from": "2026-07-21", "to": "2026-08-31"}, context="full").json()
    assert [x["odometer"] for x in late["refuels"]] == [11300, 11600]
    empty = api(app, key, plate="1AB2345", **{"from": "2026-09-01", "to": "2026-09-30"}).json()
    assert empty == {"vehicle": {"plate": "1AB2345", "name": "Škoda Octavia"}, "refuels": []}
    # samotné datum v "to" = celý den
    day = api(app, key, plate="1AB2345", **{"from": "2026-07-12", "to": "2026-07-12"}).json()
    assert len(day["refuels"]) == 1


def test_api_errors(app):
    alice = register(app, "a@example.com", "Alice")
    carol = register(app, "c@example.com", "Carol")
    add_vehicle(alice, license_plate="1AB2345")
    key = new_key(carol)
    ok = {"plate": "1AB2345", "from": "2026-07-10T06:00:00", "to": "2026-07-15T20:00:00"}
    # cizí vozidlo i neexistující SPZ -> 404 (neprozradí, že vozidlo existuje)
    assert api(app, key, **ok).status_code == 404
    assert api(app, key, **{**ok, "plate": "XXX"}).json() == {"error": "vozidlo nenalezeno"}
    for bad in ({"plate": ""}, {"from": "včera"}, {"to": ""}, {"from": "2026-07-16T00:00:00"},
                {"from": "2026-07-10T06:00:00+02:00"}, {"context": "all"}):
        r = api(app, key, **{**ok, **bad})
        assert r.status_code == 400 and "error" in r.json(), bad
    assert api(app, "tl_" + "x" * 43, **ok).status_code == 401
    assert TestClient(app).get("/api/refuels", params=ok,
                               headers={"Authorization": "Basic abc"}).status_code == 401


def vehicles_api(app, api_key, **params):
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return TestClient(app).get("/api/vehicles", params=params, headers=headers)


def test_api_vehicles(app):
    client = register(app, "vehapi@example.com")
    key = new_key(client)
    active = add_vehicle(client, model="Octavia", license_plate="1ab 2345", engine_volume="1498", engine_power="110")
    sold = add_vehicle(client, model="Fabia", license_plate="2CD3456")
    post(client, f"/vehicles/{sold}/edit", {"brand": "Škoda", "model": "Fabia", "license_plate": "2CD3456",
                                            "color_hex": "#FFFFFF", "kind": "car", "is_active": "on",
                                            "sale_date": "2025-01-10", "sale_odometer": "0"})
    add_fuel(client, active, date(2026, 7, 1), "1000", "40")
    add_fuel(client, active, date(2026, 7, 8), "1500", "30")
    post(client, "/notes/add", {"vehicle_id": active, "note_date": "2026-07-05", "note_time": "10:00",
                                "category": "Garáž", "text": "U chalupy", "odometer": "1200"})
    post(client, "/notes/add", {"vehicle_id": active, "note_date": "2026-07-09", "note_time": "08:15",
                                "text": "Škrábnutí\nNafoceno"})
    other = register(app, "other-veh@example.com")
    add_vehicle(other, model="Cizí", license_plate="9ZZ9999")

    assert vehicles_api(app, None).status_code == 401
    assert vehicles_api(app, key, status="sold").status_code == 400

    r = vehicles_api(app, key)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["status"] == "active"
    assert [v["plate"] for v in data["vehicles"]] == ["1AB2345"]
    v = data["vehicles"][0]
    assert v["id"] == str(active) and v["name"] == "Škoda Octavia" and v["active"] is True
    assert v["status"] == "active" and v["role"] == "owner" and v["odometer"] == 1500
    assert v["color_hex"] == "#FFFFFF"
    assert v["consumption"] == [{"fuel": "Benzín", "value": 6.0, "unit": "l"}]
    assert [(n["time"], n["category"], n["text"], n["odometer"]) for n in v["notes"]] == [
        ("2026-07-09T08:15:00", None, "Škrábnutí\nNafoceno", None),
        ("2026-07-05T10:00:00", "Garáž", "U chalupy", 1200)]
    assert v["notes"][0]["author"]
    assert (v["engine_volume"], v["engine_power"]) == (1498, 110)
    detail = client.get(f"/vehicles/{active}?tab=detail").text.replace(" ", " ")
    assert "1 498 cm³" in detail and "110 kW" in detail and "150 k" in detail
    assert 'value="1498"' in client.get(f"/vehicles/{active}/edit").text
    assert v["fuel_types"] == ["Benzín"] and v["vignette"] is None and v["rental"] is None

    everything = vehicles_api(app, key, status="all").json()["vehicles"]
    assert [x["plate"] for x in everything] == ["1AB2345", "2CD3456"]
    fabia = everything[1]
    assert fabia["consumption"] == [] and fabia["notes"] == []
    assert v["lender"] is None and fabia["lender"] is None
    assert fabia["engine_volume"] is None and fabia["engine_power"] is None
    assert fabia["active"] is False and fabia["status"] == "sold"
    assert fabia["sale"] == {"date": "2025-01-10", "odometer": 0, "price_czk": None}
