import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from models import FuelRecord, Vehicle


@pytest.fixture
def app(engine):
    from web.main import app
    from web.deps import get_db

    Session = sessionmaker(bind=engine)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def csrf(client, url="/login"):
    html = client.get(url).text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def register(app, email, name="Uživatel"):
    client = TestClient(app)
    token = csrf(client, "/register")
    r = client.post("/register", data={"csrf_token": token, "email": email, "name": name,
                                       "password": "heslo1234", "password_confirm": "heslo1234"},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


def post(client, url, data, follow=False):
    data = {"csrf_token": csrf(client, "/profile"), **data}
    return client.post(url, data=data, follow_redirects=follow)


def add_vehicle(client, **data):
    r = post(client, "/vehicles/add", {"brand": "Škoda", "model": "Octavia", **data})
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[1])


def add_fuel(client, vehicle_id, day, odometer, volume, **extra):
    data = {"vehicle_id": vehicle_id, "refuel_date": day.isoformat(), "refuel_time": "12:00",
            "odometer": odometer, "fuel_type": "Benzín", "volume_liters": volume, "unit_price": "40",
            "currency_code": "CZK", "full_tank": "on", **extra}
    return post(client, "/fuel-records/add", data)


def test_requires_login(app):
    client = TestClient(app)
    r = client.get("/vehicles", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=/vehicles")


def test_login_logout_and_bad_password(app):
    register(app, "a@example.com")
    client = TestClient(app)
    token = csrf(client)
    bad = client.post("/login", data={"csrf_token": token, "email": "a@example.com", "password": "xxx"})
    assert bad.status_code == 400 and "Nesprávný" in bad.text
    ok = client.post("/login", data={"csrf_token": token, "email": "a@example.com", "password": "heslo1234",
                                     "next": "//evil.example.com"}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/"
    assert client.get("/").status_code == 200
    post(client, "/logout", {})
    assert client.get("/", follow_redirects=False).status_code == 303


def test_csrf_required(app):
    client = register(app, "a@example.com")
    r = client.post("/vehicles/add", data={"brand": "X", "model": "Y"})
    assert r.status_code == 403


def test_full_flow(app, db):
    client = register(app, "alice@example.com", "Alice")
    vid = add_vehicle(client, license_plate="1a2 3456", color="modrá", color_hex="#112233",
                      vin="TMBJJ7NE1J0123456", production_year="2018")
    vehicle = db.get(Vehicle, vid)
    assert vehicle.license_plate == "1A23456" and vehicle.color_hex == "#112233"

    today = date.today()
    assert add_fuel(client, vid, today - timedelta(days=20), 10000, "40").status_code == 303
    r = add_fuel(client, vid, today - timedelta(days=10), 10500, "35")
    assert r.status_code == 303
    page = client.get(f"/vehicles/{vid}").text
    assert "Spotřeba: 7,00 l/100 km" in page  # flash zpráva po uložení

    # tachometr nesmí jít zpět
    bad = add_fuel(client, vid, today - timedelta(days=5), 9000, "20")
    assert bad.status_code == 400 and "nižší" in bad.text

    # cizí měna (kurz v testech podvržen: 1 EUR = 25 Kč) a celková cena místo ceny za litr
    r = add_fuel(client, vid, today - timedelta(days=2), 11000, "40", unit_price="", price_paid="60",
                 currency_code="eur")
    assert r.status_code == 303
    record = db.query(FuelRecord).order_by(FuelRecord.id.desc()).first()
    assert record.currency_code == "EUR" and float(record.price_local) == 1500.0
    assert float(record.unit_price) == 1.5

    # úprava vozidla - vymazání SPZ (dříve nefungovalo)
    r = post(client, f"/vehicles/{vid}/edit", {"brand": "Škoda", "model": "Octavia", "license_plate": "",
                                               "color_hex": "#112233"})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Vehicle, vid).license_plate is None

    # servis + pravidelný servis + upomínka + výdaj
    assert post(client, "/services/add", {"vehicle_id": vid, "service_date": today.isoformat(), "odometer": 11000,
                                          "service_type": "Výměna oleje", "price_paid": "2500"}).status_code == 303
    assert post(client, "/intervals/add", {"vehicle_id": vid, "service_type": "Výměna oleje",
                                           "interval_km": "15000", "interval_months": "12",
                                           "is_active": "on"}).status_code == 303
    assert post(client, "/intervals/add", {"vehicle_id": vid, "service_type": "STK", "interval_months": "24",
                                           "start_date": (today - timedelta(days=720)).isoformat(),
                                           "is_active": "on"}).status_code == 303
    assert post(client, "/reminders/add", {"vehicle_id": vid, "title": "Pojištění", "repeat": "yearly",
                                           "due_date": (today + timedelta(days=5)).isoformat(),
                                           "notify_days_before": "14", "notify_km_before": "500"}).status_code == 303
    assert post(client, "/expenses/add", {"vehicle_id": vid, "expense_date": today.isoformat(),
                                          "category": "Mytí", "price_paid": "250"}).status_code == 303

    dashboard = client.get("/").text
    assert "STK" in dashboard and "Pojištění" in dashboard  # upozornění na přehledu

    for url in ["/", "/vehicles", "/vehicles?show=all", f"/vehicles/{vid}", f"/vehicles/{vid}/edit",
                f"/vehicles/{vid}/stats", f"/vehicles/{vid}/stats?period=all",
                f"/vehicles/{vid}/stats?period={today.year}", f"/vehicles/{vid}/sharing",
                "/fuel-records", "/fuel-records?all=1&vehicle_id=%d" % vid, "/fuel-records/add",
                "/services", "/services/add", "/intervals/add", "/reminders", "/reminders?show=all",
                "/reminders/add", "/expenses", "/expenses/add", "/profile", "/offline"]:
        r = client.get(url)
        assert r.status_code == 200, url

    csv = client.get("/fuel-records/export.csv?all=1")
    assert csv.status_code == 200 and "Benzín" in csv.text
    assert client.get("/services/export.csv?all=1").status_code == 200
    assert client.get("/expenses/export.csv?all=1").status_code == 200

    # úprava a smazání tankování
    fuel_id = record.id
    assert client.get(f"/fuel-records/{fuel_id}/edit").status_code == 200
    assert post(client, f"/fuel-records/{fuel_id}/delete", {}).status_code == 303
    db.expire_all()
    assert db.query(FuelRecord).filter(FuelRecord.id == fuel_id).count() == 0

    # vyřízení opakované upomínky
    from models import Reminder
    reminder = db.query(Reminder).first()
    original_due = reminder.due_date
    assert post(client, f"/reminders/{reminder.id}/done", {"next": "/reminders"}).status_code == 303
    db.expire_all()
    assert db.get(Reminder, reminder.id).due_date.year == original_due.year + 1


def test_sharing_permissions(app, db):
    alice = register(app, "alice@example.com", "Alice")
    bob = register(app, "bob@example.com", "Bob")
    carol = register(app, "carol@example.com", "Carol")
    vid = add_vehicle(alice)
    add_fuel(alice, vid, date.today(), 1000, "40")
    fuel_id = db.query(FuelRecord).first().id

    # cizí vozidlo není vidět
    assert bob.get(f"/vehicles/{vid}").status_code == 404
    assert "Octavia" not in bob.get("/fuel-records?all=1").text

    # sdílení jen pro čtení
    assert post(alice, f"/vehicles/{vid}/sharing", {"action": "add", "email": "bob@example.com",
                                                    "role": "viewer"}).status_code == 303
    assert bob.get(f"/vehicles/{vid}").status_code == 200
    assert "Octavia" in bob.get("/fuel-records?all=1").text
    assert bob.get(f"/vehicles/{vid}/edit").status_code == 403
    assert add_fuel(bob, vid, date.today(), 1500, "30").status_code == 403  # nemá právo zápisu
    assert post(bob, f"/fuel-records/{fuel_id}/delete", {}).status_code == 403
    assert bob.get(f"/vehicles/{vid}/sharing").status_code == 403
    assert post(bob, f"/vehicles/{vid}/delete", {}).status_code == 403

    # povýšení na editora
    share_id = db.get(Vehicle, vid).shares[0].id
    post(alice, f"/vehicles/{vid}/sharing", {"action": "role", "share_id": share_id, "role": "editor"})
    assert add_fuel(bob, vid, date.today(), 1500, "30").status_code == 303
    assert post(bob, f"/vehicles/{vid}/delete", {}).status_code == 403  # mazat může jen vlastník

    # sdílení s neexistujícím uživatelem
    r = post(alice, f"/vehicles/{vid}/sharing", {"action": "add", "email": "nikdo@example.com", "role": "viewer"})
    assert r.status_code == 400

    # Carol nic nevidí; Bob může sdílení ukončit
    assert carol.get(f"/vehicles/{vid}").status_code == 404
    assert post(bob, f"/vehicles/{vid}/leave", {}).status_code == 303
    assert bob.get(f"/vehicles/{vid}").status_code == 404

    # vlastník smaže vozidlo
    assert post(alice, f"/vehicles/{vid}/delete", {}).status_code == 303
    assert alice.get(f"/vehicles/{vid}").status_code == 404


def test_pwa_files(app):
    client = TestClient(app)
    assert client.get("/manifest.webmanifest").json()["short_name"] == "Fleet"
    assert client.get("/sw.js").status_code == 200
    assert client.get("/static/icons/icon-192.png").status_code == 200


def test_fuel_filter_dates(app, db):
    client = register(app, "f@example.com")
    vid = add_vehicle(client)
    today = date.today()
    assert add_fuel(client, vid, today, 1000, "40", refuel_time="23:59").status_code == 303

    def shows(url):
        page = client.get(url)
        assert page.status_code == 200, url
        return "/fuel-records/" in page.text and "/edit" in page.text

    assert shows("/fuel-records")
    assert shows(f"/fuel-records?date_from={today.isoformat()}&date_to={today.isoformat()}")
    # nedopsaný rok z prohlížeče (0002) se ignoruje místo filtrování od roku 2
    assert shows("/fuel-records?date_from=0002-11-20")
    assert not shows(f"/fuel-records?date_to={(today - timedelta(days=1)).isoformat()}")
    # nesmyslný rok ve formuláři je chyba
    r = add_fuel(client, vid, date(2, 1, 1), 900, "10")
    assert r.status_code == 400 and "rok musí být" in r.text


def test_vignette_reminder(app, db):
    from models import Expense, Reminder

    client = register(app, "v@example.com")
    vid = add_vehicle(client)
    start = date.today()
    data = {"vehicle_id": vid, "expense_date": start.isoformat(), "category": "Dálniční známka",
            "price_paid": "2570", "vignette_variant": "year", "valid_from": start.isoformat(), "remind": "on"}
    assert post(client, "/expenses/add", data).status_code == 303
    first = db.query(Expense).one()
    assert first.valid_until == start + timedelta(days=364)
    reminder = db.get(Reminder, first.reminder_id)
    assert reminder.due_date == first.valid_until and not reminder.is_done
    assert "Dálniční známka" in client.get(f"/vehicles/{vid}").text
    assert client.get(f"/expenses/{first.id}/edit").status_code == 200

    # 10denní známka bez upomínky
    assert post(client, "/expenses/add", {**data, "vignette_variant": "10d", "remind": ""}).status_code == 303
    ten_day = db.query(Expense).order_by(Expense.id.desc()).first()
    assert ten_day.valid_until == start + timedelta(days=9) and ten_day.reminder_id is None

    # obnovení: nová roční známka uzavře upomínku té předchozí
    renewal_start = first.valid_until + timedelta(days=1)
    assert post(client, "/expenses/add", {**data, "valid_from": renewal_start.isoformat()}).status_code == 303
    db.expire_all()
    assert db.get(Reminder, reminder.id).is_done
    renewal = db.query(Expense).order_by(Expense.id.desc()).first()
    assert db.get(Reminder, renewal.reminder_id).due_date == renewal_start + timedelta(days=364)

    # smazání výdaje smaže jeho otevřenou upomínku
    renewal_reminder_id = renewal.reminder_id
    assert post(client, f"/expenses/{renewal.id}/delete", {}).status_code == 303
    db.expire_all()
    assert db.get(Reminder, renewal_reminder_id) is None

    # výdaj bez platnosti upomínku nevytváří, ani s výchozím zaškrtnutím
    count = db.query(Reminder).count()
    assert post(client, "/expenses/add", {"vehicle_id": vid, "expense_date": start.isoformat(),
                                          "category": "Mytí", "price_paid": "200", "remind": "on",
                                          "valid_from": start.isoformat()}).status_code == 303
    assert db.query(Reminder).count() == count

    # konec platnosti před začátkem
    r = post(client, "/expenses/add", {**data, "vignette_variant": "", "valid_until": (start - timedelta(days=1)).isoformat()})
    assert r.status_code == 400


def test_fleet_stats(app, db):
    client = register(app, "s@example.com")
    assert "Zatím nemáte" in client.get("/stats").text
    a = add_vehicle(client, model="Octavia")
    b = add_vehicle(client, model="Fabia")
    today = date.today()
    add_fuel(client, a, today - timedelta(days=40), 10000, "40")
    add_fuel(client, a, today - timedelta(days=10), 10600, "42")
    add_fuel(client, b, today - timedelta(days=20), 50000, "30", fuel_type="Nafta")
    for url in ["/stats", "/stats?period=all", f"/stats?period={today.year}", "/stats?period=nesmysl"]:
        r = client.get(url)
        assert r.status_code == 200, url
    page = client.get("/stats").text
    assert "Octavia" in page and "Fabia" in page and "chart-odometer" in page

    from services.stats_service import StatsService
    vehicles = [db.get(Vehicle, a), db.get(Vehicle, b)]
    summary = StatsService(db).fleet_summary(vehicles)
    assert summary["distance"] == 600
    assert set(summary["charts"]["unit_price"]) == {"Benzín", "Nafta"}
    odo = summary["charts"]["odometer"]
    # ujeto od začátku období, skutečný stav v "odo"
    assert [p["y"] for p in odo["Škoda Octavia"]] == [0, 600]
    assert [p["odo"] for p in odo["Škoda Octavia"]] == [10000, 10600]
    # cena u každého tankování (ne měsíční průměr)
    prices = summary["charts"]["unit_price"]["Benzín"]
    assert len(prices) == 2 and prices[0]["y"] == 40 and prices[0]["vehicle"] == "Škoda Octavia"
    profile = summary["rows"][0]["profile"]
    assert profile["days_between"] == 30 and profile["km_between"] == 600
    assert round(profile["km_per_year"]) == round(600 / 30 * 365.25)
    assert "Tankuje každých" in page
