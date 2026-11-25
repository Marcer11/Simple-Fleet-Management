from datetime import date

from test_web import register, post, add_vehicle, app, db  # noqa: F401
def test_service_with_multiple_items(app, db):
    from models import ServiceRecord, ServiceInterval
    from services.maintenance_service import ServiceIntervalService, ServiceRecordService
    client = register(app, "multi@example.com")
    car = add_vehicle(client)
    r = post(client, "/services/add", {"vehicle_id": car, "service_date": "2026-03-01", "odometer": "50000",
                                       "st:Výměna oleje": "on", "st:Brzdy": "on", "st:STK": "on",
                                       "service_type_other": "Stěrače, brzdy", "currency_code": "CZK"})
    assert r.status_code == 303, r.text
    record = db.query(ServiceRecord).one()
    assert record.service_type == "Výměna oleje, Brzdy, STK, Stěrače" and record.types[-1] == "Stěrače"
    # pravidelný servis se počítá i od vícepoložkového záznamu
    post(client, "/intervals/add", {"vehicle_id": car, "service_type": "Brzdy", "interval_months": "24",
                                    "is_active": "on"})
    interval = db.query(ServiceInterval).one()
    status = ServiceIntervalService(db).get_status(interval, 50000)
    assert status.last_date == date(2026, 3, 1)
    assert ServiceRecordService(db).get_last_service(car, "Brzdy").id == record.id
    assert ServiceRecordService(db).get_last_service(car, "Oprava") is None
    # filtr podle položky a nabídka vlastních položek
    page = client.get("/services?all=1&service_type=STK").text
    assert "Výměna oleje, Brzdy, STK" in page
    form = client.get(f"/services/{record.id}/edit").text
    assert 'name="st:Stěrače" value="on" checked' in form and 'name="st:Brzdy" value="on" checked' in form
    # bez položky nejde uložit
    r = post(client, "/services/add", {"vehicle_id": car, "service_date": "2026-03-02", "currency_code": "CZK"})
    assert r.status_code == 400 and "alespoň jednu" in r.text


def test_service_duration_and_distance(app, db):
    from models import ServiceRecord, Vehicle
    from services.events import collect_events
    from services.vehicle_service import VehicleService
    client = register(app, "svcdur@example.com")
    car = add_vehicle(client)
    base = {"vehicle_id": car, "st:Brzdy": "on", "currency_code": "CZK", "place": "Autoservis Novák"}
    # přes několik dní s časy
    r = post(client, "/services/add", {**base, "service_date": "2026-03-01", "service_time": "08:30", "odometer": "50000",
                                       "date_to": "2026-03-03", "time_to": "15:00", "odometer_to": "50012"})
    assert r.status_code == 303, r.text
    record = db.query(ServiceRecord).one()
    assert (record.duration, record.distance) == ("2 dny 6 h", 12)
    assert VehicleService(db).get_current_odometer(car) == 50012
    page = client.get("/services?all=1").text
    assert "v servisu 2 dny 6 h" in page and "servis najel 12\u00a0km" in page
    form = client.get(f"/services/{record.id}/edit").text
    assert 'value="15:00"' in form and 'value="50012"' in form
    # časová osa: předání a vyzvednutí
    events = collect_events(db, [db.get(Vehicle, car)], kinds=["service"])
    assert [e.title for e in events] == ["Vyzvednutí ze servisu – Autoservis Novák", "Brzdy"]
    assert events[0].odometer == 50012 and "servis najel 12 km" in events[0].detail
    assert events[1].when.hour == 8 and "do 3. 3. 2026 15:00" in events[1].detail
    # v jednom dni: jedna událost, doba v hodinách; bez časů ve dnech
    record.date_to, record.time_to, record.service_time = date(2026, 3, 1), None, None
    db.commit()
    assert record.duration == "1 den"
    events = collect_events(db, [db.get(Vehicle, car)], kinds=["service"])
    assert len(events) == 1 and "v servisu 1 den" in events[0].detail

    # kontroly
    for extra, error in [({"date_to": "2026-02-28"}, "před předáním"),
                         ({"time_to": "10:00"}, "datum vyzvednutí"),
                         ({"date_to": "2026-03-01", "service_time": "10:00", "time_to": "09:00"}, "před časem předání"),
                         ({"odometer": "100", "odometer_to": "90"}, "menší než při předání")]:
        r = post(client, "/services/add", {**base, "service_date": "2026-03-01", **extra})
        assert r.status_code == 400 and error in r.text, extra


def test_vehicle_list_status_icons(app, db):
    from models import ServiceRecord, Vehicle
    client = register(app, "icons@example.com")
    car = add_vehicle(client)
    base = {"vehicle_id": car, "st:Brzdy": "on", "currency_code": "CZK", "place": "Autoservis Novák",
            "service_date": date.today().isoformat()}
    assert post(client, "/services/add", {**base, "in_progress": "on"}).status_code == 303
    record = db.query(ServiceRecord).one()
    assert record.in_progress and db.get(Vehicle, car).active_service.id == record.id
    html = client.get("/vehicles").text
    assert "<th>Info</th>" in html and "<th>Pneu</th>" not in html
    assert 'class="in-service" title="V servisu od' in html and "Autoservis Novák" in html
    assert "V servisu od" in client.get(f"/vehicles/{car}").text
    # upozornění (upomínka po termínu)
    post(client, "/reminders/add", {"vehicle_id": car, "title": "Výměna stěračů",
                                    "due_date": "2020-01-01", "repeat": "none"})
    html = client.get("/vehicles").text
    assert "alert-icon-overdue" in html and "Výměna stěračů" in html
    # vyzvednutím servis končí (zaškrtnutí se nepoužije)
    r = post(client, f"/services/{record.id}/edit", {**base, "in_progress": "on", "date_to": base["service_date"]})
    assert r.status_code == 303, r.text
    db.expire_all()
    assert not db.get(ServiceRecord, record.id).in_progress and db.get(Vehicle, car).active_service is None
    assert 'class="in-service"' not in client.get("/vehicles").text


def test_vehicle_out_of_order_notes(app, db):
    from datetime import datetime
    from models import Vehicle, ServiceRecord
    from services.events import collect_events
    from test_api import new_key, vehicles_api
    client = register(app, "ooo@example.com")
    car = add_vehicle(client, license_plate="9OO0001")
    detail = client.get(f"/vehicles/{car}").text
    assert "category=Nepojízdné" in detail and "Opět pojízdné</a>" not in detail

    def note(day, hm, category, text=""):
        r = post(client, "/notes/add", {"vehicle_id": car, "note_date": day, "note_time": hm,
                                        "category": category, "text": text})
        assert r.status_code == 303, r.text

    note("2026-03-01", "08:00", "Nepojízdné", "nestartuje")
    v = db.get(Vehicle, car)
    assert v.out_of_order and v.out_of_order_since == datetime(2026, 3, 1, 8, 0)
    assert v.out_of_order_reason == "nestartuje"
    html = client.get("/vehicles").text
    assert ">Nepojízdné</span>" in html and "Nepojízdné od 01.03.2026 08:00 – nestartuje" in html
    assert "Opět pojízdné</a>" in client.get(f"/vehicles/{car}").text
    item = vehicles_api(app, new_key(client)).json()["vehicles"][0]
    assert item["out_of_order"] == {"since": "2026-03-01", "reason": "nestartuje"}

    # poznámka "Opět pojízdné" nepojízdnost ukončí, v časové ose je délka
    note("2026-03-03", "10:30", "Opět pojízdné")
    db.expire_all()
    assert not v.out_of_order and v.out_of_order_periods[0].duration == "2 dny 2 h"
    events = collect_events(db, [v], kinds=["note"])
    assert events[0].title == "Opět pojízdné" and events[0].icon == "car" and "nepojízdné 2 dny 2 h" in events[0].detail
    assert events[1].icon == "stop"
    assert vehicles_api(app, new_key(client)).json()["vehicles"][0]["out_of_order"] is None

    # vyzvednutí ze servisu ji ukončí také (předání do servisu ne)
    note("2026-03-10", "09:00", "Nepojízdné")
    base = {"vehicle_id": car, "st:Brzdy": "on", "currency_code": "CZK", "service_date": "2026-03-11"}
    assert post(client, "/services/add", {**base, "in_progress": "on"}).status_code == 303
    db.expire_all()
    assert v.out_of_order
    record = db.query(ServiceRecord).one()
    assert post(client, f"/services/{record.id}/edit", {**base, "date_to": "2026-03-14"}).status_code == 303
    db.expire_all()
    assert not v.out_of_order
    pickup = [e for e in collect_events(db, [v], kinds=["service"]) if e.title.startswith("Vyzvednutí")][0]
    assert "opět pojízdné (nepojízdné 4 dny)" in pickup.detail
    assert ">Nepojízdné</span>" not in client.get("/vehicles").text
    # úprava vozidla už stav nemá
    assert "out_of_order" not in client.get(f"/vehicles/{car}/edit").text
