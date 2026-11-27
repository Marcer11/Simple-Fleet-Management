from datetime import date, timedelta

from sqlalchemy import create_engine, text

from models import Expense, ServiceRecord, Tire, TireDefect, TireMount, TireSwap, Vehicle
from services.maintenance_service import collect_alerts
from services.tire_service import open_mounts, tire_stats, winter_tire_status
from test_migrations import _upgrade
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401


def add_tire(client, db, **data):
    payload = {"season": "Letní", "manufacturer": "Michelin", "model": "Primacy 4", "size": "205/55 R16 91V",
               "production_year": "2021", "quantity": "4", "rim": "alu", "new_tread_mm": "8",
               "purchase_date": "2021-04-01", "currency_code": "CZK", **data}
    r = post(client, "/tires/add", payload)
    assert r.status_code == 303, r.text
    return db.query(Tire).order_by(Tire.id.desc()).first()


def swap(client, vid, day, km, mounts=(), remove=(), treads=None, **data):
    payload = {"vehicle_id": vid, "swap_date": day.isoformat(), "odometer": km, "place": "home",
               "currency_code": "CZK", **data}
    for i, (tire, position) in enumerate(mounts):
        payload[f"mount_tire_{i}"] = tire.id
        payload[f"mount_pos_{i}"] = position
    for mount_id in remove:
        payload[f"remove_{mount_id}"] = "1"
    for mount_id, mm in (treads or {}).items():
        payload[f"tread_{mount_id}"] = mm
    return post(client, "/tire-swaps/add", payload)


def test_tires_mounts_partial_swap_and_lifetime(app, db):
    client = register(app, "p@example.com")
    car = add_vehicle(client, model="Octavia")
    other = add_vehicle(client, model="Fabia")
    summer = add_tire(client, db, price_paid="12000", expense_vehicle_id=car)
    winter = add_tire(client, db, season="Zimní", manufacturer="Nokian", model="WR", quantity="4", new_tread_mm="9")
    front = add_tire(client, db, season="Zimní", manufacturer="Nokian", model="WR", quantity="2", new_tread_mm="9")
    # nákup jako výdaj u zvoleného vozidla
    assert summer.expense.category == "Pneumatiky" and summer.expense.vehicle_id == car
    assert float(summer.price_local) == 12000

    d0 = date.today() - timedelta(days=400)
    assert swap(client, car, d0, 10000, [(summer, "all")]).status_code == 303
    m_summer = db.query(TireMount).filter_by(tire_id=summer.id).one()
    r = swap(client, car, d0 + timedelta(days=200), 22000, [(winter, "all")], treads={m_summer.id: "6"},
             place="service", service_place="Pneuservis Novák", price_paid="800")
    assert r.status_code == 303, r.text
    assert db.query(ServiceRecord).one().service_type == "Přezutí pneumatik"
    # jen přední: nový pár dopředu, zbytek zimní sady zůstane vzadu
    assert swap(client, car, d0 + timedelta(days=250), 25000, [(front, "front")]).status_code == 303
    db.expire_all()
    current = {m.tire_id: m.position for m in open_mounts(db, car)}
    assert current == {front.id: "front", winter.id: "rear"}
    # starší přezutí nejde vložit před novější
    r = swap(client, car, d0 + timedelta(days=240), 24000, [(summer, "all")])
    assert r.status_code == 400 and "novější přezutí" in r.text
    # dvě pneumatiky na stejné pozici
    r = swap(client, car, d0 + timedelta(days=260), 26000, [(summer, "all"), (front, "front")])
    assert r.status_code == 400 and "stejné pozici" in r.text

    # letní sada na jiné auto
    assert swap(client, other, d0 + timedelta(days=300), 5000, [(summer, "all")]).status_code == 303
    add_fuel(client, car, date.today() - timedelta(days=1), 30000, "40")
    add_fuel(client, other, date.today() - timedelta(days=1), 7000, "40")
    db.expire_all()
    stats = {s["tire"].id: s for s in tire_stats(db, db.query(Tire).all())}
    assert stats[summer.id]["km"] == 12000 + 2000 and stats[summer.id]["vehicles"] == ["Škoda Octavia", "Škoda Fabia"]
    assert float(stats[summer.id]["tread"]) == 6 and stats[summer.id]["status"] == "mounted"
    assert stats[winter.id]["km"] == 3000 + 5000  # celá sada 3000 km, pak vzadu 5000 km
    assert stats[front.id]["km"] == 5000
    assert round(float(stats[summer.id]["wear"]), 4) == round(2 / 12000 * 1000, 4)

    page = client.get("/tires").text
    assert "Teď na vozidlech" in page and "Zadní náprava" in page and "Přední náprava" in page
    assert "Pneumatiky" in client.get("/").text  # položka menu
    detail = client.get(f"/vehicles/{car}").text
    assert "Nokian WR" in detail and "Zadní náprava" in detail
    timeline = client.get("/timeline?all=1&kind=tires").text
    assert "Přezutí pneumatik" in timeline and "nasazeno: Zimní Nokian WR (přední náprava)" in timeline
    assert client.get(f"/tires/{summer.id}/edit").status_code == 200

    # smazat lze jen přezutí, jehož pneumatiky nikdo nesundal
    first = db.query(TireSwap).order_by(TireSwap.id).first()
    r = post(client, f"/tire-swaps/{first.id}/delete", {}, follow=True)
    assert "nejdřív smažte novější" in r.text
    last = db.query(TireSwap).order_by(TireSwap.id.desc()).first()
    post(client, f"/tire-swaps/{last.id}/delete", {})
    db.expire_all()
    # letní sada je zpět uskladněná (na Octavii ji sundalo zimní přezutí)
    assert db.get(Tire, summer.id).open_mount is None

    # úprava přezutí v servisu na doma zruší servisní záznam
    service_swap = db.query(TireSwap).filter_by(place="service").one()
    r = post(client, f"/tire-swaps/{service_swap.id}/edit",
             {"vehicle_id": car, "swap_date": service_swap.swap_date.isoformat(), "odometer": 22000,
              "place": "home", "currency_code": "CZK", f"tread_{m_summer.id}": "5.5"})
    assert r.status_code == 303, r.text
    assert db.query(ServiceRecord).count() == 0
    db.expire_all()
    assert float(db.get(TireMount, m_summer.id).removed_tread_mm) == 5.5


def test_defects_and_delete(app, db):
    client = register(app, "d@example.com")
    car = add_vehicle(client)
    tire = add_tire(client, db, quantity="2")
    swap(client, car, date.today() - timedelta(days=10), 1000, [(tire, "rear")])
    r = post(client, "/tire-defects/add", {"tire_id": tire.id, "defect_date": date.today().isoformat(),
                                           "position": "Levá zadní", "description": "Hřebík – zalepeno",
                                           "price_paid": "300", "currency_code": "CZK"})
    assert r.status_code == 303, r.text
    defect = db.query(TireDefect).one()
    # vozidlo se dohledalo z nasazení
    assert defect.vehicle_id == car and defect.expense.description == "Oprava pneumatiky: Hřebík – zalepeno"
    assert "Poškození pneu: Hřebík" in client.get("/timeline?all=1").text
    # bez nasazení a vozidla nejde zapsat cenu
    spare = add_tire(client, db, quantity="1")
    r = post(client, "/tire-defects/add", {"tire_id": spare.id, "defect_date": date.today().isoformat(),
                                           "description": "Boule", "price_paid": "100", "currency_code": "CZK"})
    assert r.status_code == 400 and "vyberte vozidlo" in r.text

    post(client, f"/tires/{tire.id}/delete", {})
    assert db.query(TireDefect).count() == 0 and db.query(TireMount).count() == 0
    assert db.query(TireSwap).count() == 0
    assert db.query(Expense).filter(Expense.description.like("Oprava%")).count() == 0


def test_tire_access(app, db):
    alice = register(app, "a@example.com")
    bob = register(app, "b@example.com")
    add_vehicle(alice)
    bob_car = add_vehicle(bob)
    tire = add_tire(alice, db)
    assert bob.get(f"/tires/{tire.id}/edit").status_code == 404
    r = swap(bob, bob_car, date.today(), 100, [(tire, "all")])
    assert r.status_code == 400 and "Pneumatika nenalezena" in r.text
    assert db.query(TireSwap).count() == 0
    assert "Primacy" not in bob.get("/tires").text
    r = post(alice, "/tires/add", {"season": "Jarní", "manufacturer": "X", "quantity": "2"})
    assert r.status_code == 400


def test_winter_tire_alert(app, db):
    client = register(app, "w@example.com")
    car = add_vehicle(client)
    summer = add_tire(client, db)
    swap(client, car, date(2026, 4, 1), 1000, [(summer, "all")])
    vehicle = db.get(Vehicle, car)
    assert winter_tire_status(date(2026, 7, 1)) is None
    assert winter_tire_status(date(2026, 10, 20)).level == "warning"
    assert winter_tire_status(date(2027, 2, 1)).due_date == date(2026, 11, 1)
    alerts = [a for a in collect_alerts(db, [vehicle], today=date(2026, 11, 24)) if a.kind == "tires"]
    assert len(alerts) == 1 and alerts[0].status.level == "overdue"
    winter = add_tire(client, db, season="Zimní", manufacturer="Nokian")
    swap(client, car, date(2026, 11, 2), 5000, [(winter, "all")])
    assert not [a for a in collect_alerts(db, [vehicle], today=date(2026, 11, 24)) if a.kind == "tires"]


def test_migration_converts_tire_sets(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tires.db'}")
    with engine.begin() as conn:
        _upgrade(conn, "0009_tires")
        conn.execute(text("INSERT INTO users (id, email, name, password_hash, is_active) "
                          "VALUES (1, 'a@x.cz', 'A', 'x', 1)"))
        conn.execute(text("INSERT INTO vehicles (id, owner_id, brand, model, color_hex, is_active) "
                          "VALUES (1, 1, 'Škoda', 'Octavia', '#FFFFFF', 1)"))
        conn.execute(text("INSERT INTO tire_sets (id, vehicle_id, season, manufacturer, quantity, rim) VALUES "
                          "(1, 1, 'Letní', 'Michelin', 4, 'alu'), (2, 1, 'Zimní', 'Nokian', 4, 'steel')"))
        conn.execute(text("INSERT INTO tire_changes (id, vehicle_id, change_date, odometer, tire_set_id, place, "
                          "removed_tread_mm) VALUES (1, 1, '2025-04-01', 1000, 1, 'home', NULL), "
                          "(2, 1, '2025-11-01', 9000, 2, 'home', 6.5)"))
        conn.execute(text("INSERT INTO tire_damages (vehicle_id, tire_set_id, damage_date, description) "
                          "VALUES (1, 2, '2025-12-01', 'Hřebík')"))
        _upgrade(conn)
        tires = conn.execute(text("SELECT id, owner_id, season, quantity FROM tires ORDER BY id")).fetchall()
        assert [(t.owner_id, t.season, t.quantity) for t in tires] == [(1, "Letní", 4), (1, "Zimní", 4)]
        mounts = conn.execute(text("SELECT tire_id, position, mounted_km, removed_km, removed_tread_mm "
                                   "FROM tire_mounts ORDER BY id")).fetchall()
        assert [(m.position, m.mounted_km, m.removed_km) for m in mounts] == [("all", 1000, 9000), ("all", 9000, None)]
        assert float(mounts[0].removed_tread_mm) == 6.5
        assert conn.execute(text("SELECT COUNT(*) FROM tire_swaps")).scalar() == 2
        assert conn.execute(text("SELECT description FROM tire_defects")).scalar() == "Hřebík"
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert not {"tire_sets", "tire_changes", "tire_damages"} & tables


def test_per_wheel_treads_and_moto(app, db):
    client = register(app, "k@example.com")
    car = add_vehicle(client, model="Octavia")
    moto = add_vehicle(client, brand="Honda", model="CBF", kind="moto")
    assert db.get(Vehicle, moto).kind == "moto" and db.get(Vehicle, car).kind == "car"
    winter = add_tire(client, db, season="Zimní", new_tread_mm="9")
    summer = add_tire(client, db)
    d0 = date.today() - timedelta(days=100)
    swap(client, car, d0, 1000, [(winter, "all")])
    mount = db.query(TireMount).filter_by(tire_id=winter.id).one()
    # dezén po kolech - přední jiný než zadní; ukládá se i nejmenší hodnota
    r = swap(client, car, d0 + timedelta(days=50), 6000, [(summer, "all")],
             **{f"tread_{mount.id}_fl": "5,5", f"tread_{mount.id}_fr": "5.6",
                f"tread_{mount.id}_rl": "7", f"tread_{mount.id}_rr": "7"})
    assert r.status_code == 303, r.text
    db.expire_all()
    mount = db.get(TireMount, mount.id)
    assert mount.tread_map == {"fl": "5.5", "fr": "5.6", "rl": "7.0", "rr": "7.0"}
    assert float(mount.removed_tread_mm) == 5.5
    assert "LP 5,5 · PP 5,6 · LZ 7,0 · PZ 7,0" in client.get("/tires").text
    # úprava přezutí - dezén po kolech jde opravit
    s = mount.removed_swap
    r = post(client, f"/tire-swaps/{s.id}/edit", {"vehicle_id": car, "swap_date": s.swap_date.isoformat(),
                                                  "odometer": 6000, "place": "home", "currency_code": "CZK",
                                                  f"tread_{mount.id}_fl": "6", f"tread_{mount.id}_fr": "6"})
    assert r.status_code == 303, r.text
    db.expire_all()
    assert db.get(TireMount, mount.id).tread_map == {"fl": "6.0", "fr": "6.0"}

    # motorka: jen přední / zadní / obě kola; popisky "kolo"
    # pneumatika pro auto na motorku nejde a v nabídce přezutí motorky není
    r = swap(client, moto, d0, 500, [(summer, "front")])
    assert r.status_code == 400 and "je pro auto" in r.text
    front = add_tire(client, db, quantity="1", size="120/70 ZR17", kind="moto")
    r = swap(client, moto, d0, 500, [(front, "fl")])
    assert r.status_code == 400 and "Na motorce" in r.text
    assert swap(client, moto, d0, 500, [(front, "front")]).status_code == 303
    page = client.get(f"/tire-swaps/add?vehicle_id={moto}").text
    assert "Přední kolo" in page and "Levé přední" not in page and '"kind": "moto"' in page
    assert f">{front.full_label} (" in page and f">{summer.full_label} (" not in page
    # motorka nedostane upozornění na zimní pneumatiky
    alerts = [a for a in collect_alerts(db, [db.get(Vehicle, moto)], today=date(2026, 12, 1)) if a.kind == "tires"]
    assert not alerts
    # ikony typu pneumatik na přehledu a v seznamu vozidel
    assert "Letní pneumatiky: Letní Michelin Primacy 4 (všechna kola)" in client.get("/vehicles").text


def test_vehicle_tire_sizes(app, db):
    from models.tire import size_core, size_fits
    assert size_core("225/45 ZR17 91W") == "225/45R17" and size_core("120/70-17") == "120/70R17"
    assert size_fits("205/55 R16 91V", ["přední 205/55R16 94H"]) is True
    assert size_fits("195/65 R15", ["205/55 R16"]) is False and size_fits("", ["205/55 R16"]) is None
    client = register(app, "s@example.com")
    car = add_vehicle(client, model="Astra", tire_sizes="205/55 R16 91V\r\n  225/45   R17 91W \r\n205/55 r16 91v")
    vehicle = db.get(Vehicle, car)
    assert vehicle.tire_size_list == ["205/55 R16 91V", "225/45 R17 91W"]
    # rozměry dle TP jsou jen údaj u vozidla - nikam se nepropisují
    form = client.get("/tires/add").text
    assert "vehicle-sizes" not in form and "225/45 R17 91W" not in form
    assert "205/55 R16 91V" in client.get(f"/vehicles/{car}?tab=detail").text
    wrong = add_tire(client, db, size="195/65 R15 91H")
    page = client.get(f"/tire-swaps/add?vehicle_id={car}").text
    assert '"fits"' not in page and "dle TP" not in page
    r = swap(client, car, date.today(), 1000, [(wrong, "all")])
    assert r.status_code == 303
    assert "technickém průkazu" not in client.get(f"/vehicles/{car}").text
    # univerzální pneumatiky: svisle rozdělená ikona (půl vločky, půl slunce)
    allseason = add_tire(client, db, season="Univerzální")
    swap(client, car, date.today(), 1000, [(allseason, "all")])
    dash = client.get("/vehicles").text
    assert "Univerzální pneumatiky:" in dash and 'class="season-winter"' in dash and 'class="season-summer"' in dash


def test_tread_checks_and_wear_warning(app, db):
    from models import TireTreadCheck
    client = register(app, "tc@example.com")
    car = add_vehicle(client, model="Octavia")
    summer = add_tire(client, db, new_tread_mm="8", quantity="4")
    d0 = date.today() - timedelta(days=300)
    swap(client, car, d0, 10000, [(summer, "all")])
    mount = db.query(TireMount).filter_by(tire_id=summer.id).one()
    page = client.get(f"/tire-checks/add?vehicle_id={car}").text
    assert f'name="tread_{mount.id}_fl"' in page and f'name="tread_{mount.id}_rr"' in page and "▲ předek" in page

    def check(day, km, **treads):
        payload = {"vehicle_id": car, "check_date": day.isoformat(), "odometer": km, "note": "pravidelná"}
        payload.update({f"tread_{mount.id}_{w}": v for w, v in treads.items()})
        return post(client, "/tire-checks/add", payload)

    # bez hodnot nejde uložit, km musí sedět s ostatními záznamy
    assert "alespoň u jednoho kola" in check(d0 + timedelta(days=10), 11000).text
    assert check(d0 + timedelta(days=100), 5000, fl="7").status_code == 400
    r = check(d0 + timedelta(days=100), 20000, fl="6,5", fr="6.6", rl="7", rr="7.1")
    assert r.status_code == 303, r.text
    add_fuel(client, car, date.today() - timedelta(days=1), 35000, "40")
    db.expire_all()
    stats = tire_stats(db, [db.get(Tire, summer.id)])[0]
    # nejmenší hodnota z kol, opotřebení od nového dezénu: 1,5 mm na 10 000 km
    assert float(stats["tread"]) == 6.5 and round(float(stats["wear"]), 3) == 0.15
    # do 1,6 mm zbývá 4,9 mm ≈ 32 666 km od kontroly, od té doby najeto 15 000 km
    assert stats["remaining_km"] == 32666 - 15000

    # druhé měření - vzorek se blíží konci: upozornění v přehledu pneumatik
    r = check(date.today(), 35000, fl="2.2", fr="2.3", rl="3", rr="3")
    assert r.status_code == 303, r.text
    db.expire_all()
    stats = tire_stats(db, [db.get(Tire, summer.id)])[0]
    assert stats["remaining_km"] < 5000 and stats["warnings"][0][0] == "warning"
    tires_page = client.get("/tires").text.replace("\xa0", " ")
    assert "Pozor na" in tires_page and "vzorek dojde za" in tires_page
    assert "Kontroly dezénu" in tires_page and "LP 2,2 · PP 2,3 · LZ 3,0 · PZ 3,0" in tires_page
    assert 'aria-label="Letní pneumatiky"' in tires_page  # ikona místo nápisu
    timeline = client.get("/timeline?all=1&kind=tires").text
    assert "Kontrola dezénu" in timeline and "Letní Michelin Primacy 4: LP 2,2" in timeline

    # úprava a smazání
    c = db.query(TireTreadCheck).order_by(TireTreadCheck.id.desc()).first()
    edit_page = client.get(f"/tire-checks/{c.id}/edit").text
    assert 'value="2.2"' in edit_page and "naposledy 6,5 mm" in edit_page
    r = post(client, f"/tire-checks/{c.id}/edit", {"vehicle_id": car, "check_date": c.check_date.isoformat(),
                                                   "odometer": 35000, f"tread_{mount.id}_fl": "4"})
    assert r.status_code == 303, r.text
    db.expire_all()
    assert [float(x.tread_mm) for x in db.get(TireTreadCheck, c.id).readings] == [4.0]
    post(client, f"/tire-checks/{c.id}/delete", {})
    assert db.query(TireTreadCheck).count() == 1
    # smazáním pneumatiky zmizí i její kontroly
    post(client, f"/tires/{summer.id}/delete", {})
    assert db.query(TireTreadCheck).count() == 0


def test_tread_check_moto(app, db):
    client = register(app, "tm@example.com")
    moto = add_vehicle(client, brand="Honda", model="CBF", kind="moto")
    front = add_tire(client, db, quantity="1", kind="moto")
    rear = add_tire(client, db, quantity="1", kind="moto")
    swap(client, moto, date.today() - timedelta(days=30), 1000, [(front, "front"), (rear, "rear")])
    page = client.get(f"/tire-checks/add?vehicle_id={moto}").text
    assert "Nákres motorky" in page and "Přední kolo" in page.replace("přední kolo", "Přední kolo")
    fm = db.query(TireMount).filter_by(tire_id=front.id).one()
    rm = db.query(TireMount).filter_by(tire_id=rear.id).one()
    r = post(client, "/tire-checks/add", {"vehicle_id": moto, "check_date": date.today().isoformat(),
                                          "odometer": 3000, f"tread_{fm.id}_f": "4", f"tread_{rm.id}_r": "3,5"})
    assert r.status_code == 303, r.text
    assert "P 4,0" in client.get("/tires").text


def test_custom_min_tread_and_retired_reasons(app, db):
    client = register(app, "mt@example.com")
    moto = add_vehicle(client, brand="Honda", model="CBF", kind="moto")
    car_winter = add_tire(client, db, season="Zimní", quantity="4", new_tread_mm="8")
    assert car_winter.legal_min_tread == 4.0 and car_winter.min_tread == 4.0
    winter = add_tire(client, db, season="Zimní", quantity="1", new_tread_mm="6", kind="moto")
    assert winter.legal_min_tread == 1.6  # motorka: 1,6 mm i u zimních
    swap(client, moto, date.today() - timedelta(days=30), 1000, [(winter, "front")])
    db.expire_all()
    winter = db.get(Tire, winter.id)
    assert winter.is_moto and winter.legal_min_tread == 1.6  # motorka: 1,6 mm i u zimních
    stats = tire_stats(db, [winter])[0]
    assert not any("minim" in text for _, text in stats["warnings"])

    # vlastní minimum (vyšší než zákonné) - hlídá se místo zákonného
    page = client.get(f"/tires/{winter.id}/edit").text
    assert 'name="min_tread_mm"' in page and 'placeholder="zákonné 1,6"' in page.replace("\xa0", " ")
    assert '<datalist id="retired-reasons">' in page and '<option value="Opotřebení">' in page
    base = {"season": "Zimní", "kind": "moto", "manufacturer": "Michelin", "quantity": "1",
            "new_tread_mm": "6", "currency_code": "CZK"}
    r = post(client, f"/tires/{winter.id}/edit", {**base, "kind": "car"})
    assert r.status_code == 400 and "nasazená na motorce" in r.text
    r = post(client, f"/tires/{winter.id}/edit", {**base, "min_tread_mm": "7"})
    assert r.status_code == 400 and "menší než dezén při nákupu" in r.text
    r = post(client, f"/tires/{winter.id}/edit", {**base, "min_tread_mm": "6,5", "new_tread_mm": ""})
    assert r.status_code == 303, r.text
    db.expire_all()
    winter = db.get(Tire, winter.id)
    assert float(winter.min_tread_mm) == 6.5 and winter.min_tread == 6.5
    r = post(client, f"/tires/{winter.id}/edit", {**base, "min_tread_mm": "3"})
    assert r.status_code == 303, r.text
    db.expire_all()
    winter = db.get(Tire, winter.id)
    assert tire_stats(db, [winter])[0]["warnings"] == []
    # dezén 3,5 mm: blíží se nastavenému minimu 3 mm
    fm = db.query(TireMount).filter_by(tire_id=winter.id).one()
    r = post(client, "/tire-checks/add", {"vehicle_id": moto, "check_date": date.today().isoformat(),
                                          "odometer": 2000, f"tread_{fm.id}_f": "3,5"})
    assert r.status_code == 303, r.text
    db.expire_all()
    stats = tire_stats(db, [db.get(Tire, winter.id)])[0]
    assert stats["warnings"][0] == ("warning", "dezén 3,5 mm – blíží se nastavenému minimu 3,0 mm")
    fm.tire.min_tread_mm = 4
    db.commit()
    stats = tire_stats(db, [db.get(Tire, winter.id)])[0]
    assert stats["warnings"][0] == ("danger", "dezén 3,5 mm – pod nastaveným minimem 4,0 mm")

    # důvod vyřazení: nabídka + dříve použité vlastní důvody
    r = post(client, f"/tires/{winter.id}/edit", {**base, "retired_date": date.today().isoformat(),
                                                   "retired_reason": "Prasklý bok"})
    assert r.status_code == 303, r.text
    page = client.get(f"/tires/{winter.id}/edit").text
    assert '<option value="Prodej">' in page and '<option value="Prasklý bok">' in page
