from datetime import date, timedelta

from models import Expense, ServiceRecord, TireChange, TireDamage, TireSet, Vehicle
from services.maintenance_service import collect_alerts
from services.tire_service import tire_overview, winter_tire_status
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401


def add_set(client, vid, **data):
    payload = {"vehicle_id": vid, "season": "Letní", "manufacturer": "Michelin", "model": "Primacy 4",
               "size": "205/55 R16 91V", "production_year": "2021", "quantity": "4", "rim": "alu",
               "new_tread_mm": "8", "purchase_date": "2021-04-01", "currency_code": "CZK", **data}
    r = post(client, "/tires/add", payload)
    assert r.status_code == 303, r.text
    return r


def change(client, vid, set_id, day, km, **data):
    return post(client, "/tire-changes/add", {"vehicle_id": vid, "tire_set_id": set_id, "change_date": day.isoformat(),
                                               "odometer": km, "place": "home", "currency_code": "CZK", **data})


def test_tire_sets_changes_and_lifetime(app, db):
    client = register(app, "p@example.com")
    vid = add_vehicle(client)
    r = add_set(client, vid, price_paid="12000")
    assert r.headers["location"] == f"/tires?vehicle_id={vid}"
    add_set(client, vid, season="Zimní", manufacturer="Nokian", model="WR Snowproof", rim="steel",
            new_tread_mm="9", price_paid="10000")
    summer = db.query(TireSet).filter_by(season="Letní").one()
    winter = db.query(TireSet).filter_by(season="Zimní").one()
    # nákup = výdaj Pneumatiky
    assert summer.expense.category == "Pneumatiky" and float(summer.expense.price_local) == 12000

    d0 = date.today() - timedelta(days=400)
    assert change(client, vid, summer.id, d0, 10000).status_code == 303
    assert change(client, vid, winter.id, d0 + timedelta(days=200), 22000, place="service",
                  service_place="Pneuservis Novák", price_paid="800", removed_tread_mm="6").status_code == 303
    assert change(client, vid, summer.id, d0 + timedelta(days=350), 30000, removed_tread_mm="7.5").status_code == 303
    add_fuel(client, vid, date.today() - timedelta(days=1), 33000, "40")

    # přezutí v servisu = servisní záznam s cenou
    service = db.query(ServiceRecord).one()
    assert service.service_type == "Přezutí pneumatik" and service.place == "Pneuservis Novák"
    assert float(service.price_local) == 800
    # nižší stav tachometru než předchozí přezutí -> chyba
    r = change(client, vid, winter.id, d0 + timedelta(days=360), 29000)
    assert r.status_code == 400 and "nižší než u přezutí" in r.text

    vehicle = db.get(Vehicle, vid)
    overview = {r["set"].season: r for r in tire_overview(db, vehicle, 33000)}
    s, w = overview["Letní"], overview["Zimní"]
    assert s["status"] == "mounted" and w["status"] == "stored"
    assert s["km"] == 12000 + 3000 and s["seasons"] == 2
    assert w["km"] == 8000 and w["seasons"] == 1
    assert float(w["tread"]) == 7.5 and round(float(w["wear"]), 3) == round(1.5 / 8000 * 1000, 3)
    assert w["remaining_km"] == int((7.5 - 4.0) / (1.5 / 8000 * 1000) * 1000)
    assert float(s["tread"]) == 6.0
    assert float(s["cost"]) == 12000

    page = client.get(f"/tires?vehicle_id={vid}").text
    assert "Nasazeno" in page and "Uskladněno" in page and "Pneuservis Novák" in page
    detail = client.get(f"/vehicles/{vid}").text
    assert "Pneumatiky" in detail and "Michelin Primacy 4" in detail
    timeline = client.get("/timeline?all=1").text
    assert "Přezutí: Zimní Nokian WR Snowproof" in timeline
    # servisní záznam přezutí se na časové ose neopakuje
    assert timeline.count("Přezutí pneumatik") == 0

    # poškození s cenou opravy -> výdaj
    r = post(client, "/tire-damages/add", {"vehicle_id": vid, "tire_set_id": summer.id,
                                           "damage_date": date.today().isoformat(), "position": "Levá přední",
                                           "description": "Hřebík – zalepeno", "price_paid": "300",
                                           "currency_code": "CZK"})
    assert r.status_code == 303, r.text
    damage = db.query(TireDamage).one()
    assert damage.expense.description == "Oprava pneumatiky: Hřebík – zalepeno"
    assert "Poškození pneu: Hřebík" in client.get("/timeline?all=1").text

    # změna ceny nákupu upraví výdaj, smazání ceny výdaj smaže
    edit = {"vehicle_id": vid, "season": "Letní", "manufacturer": "Michelin", "model": "Primacy 4", "quantity": "4",
            "rim": "alu", "purchase_date": "2021-04-01", "currency_code": "CZK", "price_paid": "12500"}
    assert post(client, f"/tires/{summer.id}/edit", edit).status_code == 303
    db.expire_all()
    assert float(db.get(TireSet, summer.id).expense.price_local) == 12500
    assert post(client, f"/tires/{summer.id}/edit", {**edit, "price_paid": ""}).status_code == 303
    db.expire_all()
    assert db.get(TireSet, summer.id).expense is None

    # přezutí doma po úpravě zruší servisní záznam
    winter_change = db.query(TireChange).filter_by(place="service").one()
    r = post(client, f"/tire-changes/{winter_change.id}/edit",
             {"vehicle_id": vid, "tire_set_id": winter.id, "change_date": winter_change.change_date.isoformat(),
              "odometer": 22000, "place": "home", "removed_tread_mm": "6", "currency_code": "CZK"})
    assert r.status_code == 303, r.text
    assert db.query(ServiceRecord).count() == 0

    # smazání sady smaže i její přezutí, poškození a výdaj za opravu
    post(client, f"/tires/{summer.id}/delete", {})
    assert db.query(TireSet).count() == 1 and db.query(TireDamage).count() == 0
    assert db.query(Expense).filter(Expense.description.like("Oprava%")).count() == 0


def test_tire_access_and_validation(app, db):
    alice = register(app, "a@example.com")
    bob = register(app, "b@example.com")
    vid = add_vehicle(alice)
    other = add_vehicle(bob)
    add_set(alice, vid)
    tire_set = db.query(TireSet).one()
    assert bob.get(f"/tires/{tire_set.id}/edit").status_code in (403, 404)
    # cizí sada nejde nasadit na vlastní vozidlo
    r = change(bob, other, tire_set.id, date.today(), 100)
    assert r.status_code == 400 and "sadu pneumatik tohoto vozidla" in r.text
    r = post(alice, "/tires/add", {"vehicle_id": vid, "season": "Jarní", "manufacturer": "X", "quantity": "4"})
    assert r.status_code == 400
    assert "Primacy" not in bob.get("/tires").text


def test_winter_tire_alert(app, db):
    client = register(app, "w@example.com")
    vid = add_vehicle(client)
    add_set(client, vid)
    summer = db.query(TireSet).one()
    change(client, vid, summer.id, date(2026, 4, 1), 1000)
    vehicle = db.get(Vehicle, vid)

    assert winter_tire_status(date(2026, 7, 1)) is None
    assert winter_tire_status(date(2026, 10, 20)).level == "warning"
    assert winter_tire_status(date(2027, 2, 1)).due_date == date(2026, 11, 1)

    alerts = [a for a in collect_alerts(db, [vehicle], today=date(2026, 11, 24)) if a.kind == "tires"]
    assert len(alerts) == 1 and alerts[0].status.level == "overdue"
    assert not [a for a in collect_alerts(db, [vehicle], today=date(2026, 7, 1)) if a.kind == "tires"]

    # po přezutí na zimní upozornění zmizí
    add_set(client, vid, season="Zimní", manufacturer="Nokian")
    winter = db.query(TireSet).filter_by(season="Zimní").one()
    change(client, vid, winter.id, date(2026, 11, 2), 5000)
    assert not [a for a in collect_alerts(db, [vehicle], today=date(2026, 11, 24)) if a.kind == "tires"]
