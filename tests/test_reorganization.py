"""Univerzální servisní intervaly, prodaná vozidla, graf km, výchozí obrazovka a časová osa."""
from datetime import date, timedelta

from models import DefaultServiceInterval, ServiceInterval, Vehicle
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401


def test_default_intervals_apply_unless_vehicle_overrides(app, db):
    from services.maintenance_service import ServiceIntervalService, collect_alerts
    client = register(app, "int@example.com")
    car = add_vehicle(client, model="Octavia")
    moto = add_vehicle(client, model="MT-07", kind="moto")
    assert "Přidat doporučené" in client.get("/service-intervals").text
    r = post(client, "/service-intervals/suggested", {})
    assert r.status_code == 303
    names = {i.service_type for i in db.query(DefaultServiceInterval)}
    assert {"Výměna oleje", "Rozvody", "STK"} <= names
    # duplicita se nepřidá
    r = post(client, "/service-intervals", {"service_type": "výměna oleje", "interval_months": "6"})
    assert r.status_code == 400 and "už máte" in r.text
    r = post(client, "/service-intervals", {"service_type": "Řetěz", "vehicle_kind": "moto", "interval_km": "1000"})
    assert r.status_code == 303

    vehicles = [db.get(Vehicle, car), db.get(Vehicle, moto)]
    effective = ServiceIntervalService(db).effective_for_vehicles(vehicles)
    by_vehicle = {(i.vehicle_id, i.service_type) for i in effective}
    assert (car, "Rozvody") in by_vehicle and (moto, "Rozvody") not in by_vehicle  # rozvody jen auta
    assert (moto, "Řetěz") in by_vehicle and (car, "Řetěz") not in by_vehicle

    # olej před 13 měsíci -> univerzální interval 12 měsíců je po termínu
    old = (date.today() - timedelta(days=400)).isoformat()
    post(client, "/services/add", {"vehicle_id": car, "service_date": old, "odometer": "10000",
                                   "st:Výměna oleje": "on", "currency_code": "CZK"})
    alerts = [a for a in collect_alerts(db, vehicles) if a.kind == "interval"]
    assert any(a.vehicle.id == car and a.title == "Výměna oleje" and a.status.level == "overdue" for a in alerts)
    detail = client.get(f"/vehicles/{car}?tab=service").text
    assert "univerzální" in detail and "/intervals/add?vehicle_id=%d&amp;service_type=V%%C3%%BDm%%C4%%9Bna%%20oleje" % car in detail

    # vlastní interval vozidla má přednost (vypnutý interval univerzální vypne)
    post(client, "/intervals/add", {"vehicle_id": car, "service_type": "Výměna oleje", "interval_months": "24"})
    alerts = [a for a in collect_alerts(db, vehicles) if a.kind == "interval" and a.title == "Výměna oleje"]
    assert not alerts
    own = db.query(ServiceInterval).one()
    post(client, f"/intervals/{own.id}/edit", {"vehicle_id": car, "service_type": "Výměna oleje",
                                               "interval_months": "24"})  # bez is_active = vypnuto
    effective = ServiceIntervalService(db).effective_for_vehicles([db.get(Vehicle, car)])
    assert not [i for i in effective if i.service_type == "Výměna oleje"]

    # cizí uživatel univerzální interval nevidí ani neupraví
    other = register(app, "other@example.com")
    default = db.query(DefaultServiceInterval).first()
    assert other.get(f"/service-intervals/{default.id}/edit").status_code == 404
    assert "<strong>Rozvody</strong>" not in other.get("/service-intervals").text


def test_sold_vehicle_is_not_active(app, db):
    client = register(app, "sold@example.com")
    sold = add_vehicle(client, model="Fabia", sale_date=(date.today() - timedelta(days=3)).isoformat())
    car = add_vehicle(client, model="Octavia")
    assert db.get(Vehicle, sold).is_active is False
    page = client.get("/vehicles?show=active").text
    assert "Octavia" in page and "Fabia" not in page
    assert "Prodáno" in client.get("/vehicles").text
    # zapsaný prodej u existujícího vozidla ho vyřadí
    r = post(client, f"/vehicles/{car}/edit", {"brand": "Škoda", "model": "Octavia",
                                               "sale_date": date.today().isoformat()})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Vehicle, car).is_active is False and "Octavia" not in client.get("/vehicles?show=active").text


def test_vehicle_list_without_owner_column(app):
    client = register(app, "list@example.com")
    add_vehicle(client)
    page = client.get("/vehicles").text
    assert "Přístup" not in page and "Vlastník" not in page and "Náklady" in page


def test_odometer_chart(app, db):
    from services.stats_service import StatsService
    client = register(app, "odo@example.com")
    car = add_vehicle(client)
    add_fuel(client, car, date(2026, 1, 10), 1000, "40")
    add_fuel(client, car, date(2026, 3, 10), 3000, "40")
    charts = StatsService(db).odometer_charts(car)
    assert [p["y"] for p in charts["odometer"]] == [1000, 3000]
    assert charts["monthly_km_labels"] == ["2026-01", "2026-02", "2026-03"]
    assert sum(charts["monthly_km"]) == 2000
    page = client.get(f"/vehicles/{car}/stats?period=all").text
    assert 'id="chart-odometer"' in page and 'id="chart-monthly-km"' in page


def test_dashboard_alerts_and_timeline(app, db):
    client = register(app, "dash@example.com")
    car = add_vehicle(client)
    add_fuel(client, car, date.today() - timedelta(days=2), 1000, "40")
    post(client, "/notes/add", {"vehicle_id": car, "note_date": date.today().isoformat(), "note_time": "10:00",
                                "category": "Nehoda", "text": "ťukanec na parkovišti"})
    page = client.get("/").text
    assert page.index("Upozornění") < page.index('id="timeline"')
    assert 'id="timeline-filter" hidden' in page and 'data-toggle="timeline-filter"' in page
    assert 'aria-label="Tankování"' in page  # ikona události
    assert "tl-note" in page and "ťukanec" in page
    # poznámka u záznamu (servis) se v časové ose neukazuje - jen v detailu záznamu
    assert post(client, "/services/add", {"vehicle_id": car, "service_date": date.today().isoformat(),
                                          "odometer": 1100, "service_type": "Výměna oleje", "price_paid": "2500",
                                          "note": "dlouhá poznámka mechanika"}).status_code == 303
    page = client.get("/").text
    assert "Výměna oleje" in page and "dlouhá poznámka mechanika" not in page
    # stará adresa časové osy přesměruje i s filtrem
    r = client.get(f"/timeline?vehicle_id={car}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/?vehicle_id={car}#timeline"
    filtered = client.get(f"/?vehicle_id={car}&kind=fuel").text
    assert "ťukanec" not in filtered and "Zrušit filtr" in filtered


def test_forms_without_examples(app):
    client = register(app, "form@example.com")
    car = add_vehicle(client)
    for url in ("/vehicles/add", f"/fuel-records/add?vehicle_id={car}", "/tires/add", "/notes/add"):
        html = client.get(url).text
        assert "např." not in html and 'class="help">' not in html.replace('class="help" id', "")


def test_odometer_chart_purchase_and_sale_points(app, db):
    """Nákup a prodej jsou body grafu; 0 km je platný stav, prázdné pole bod nevytvoří."""
    from services.stats_service import StatsService
    client = register(app, "buy@example.com")
    new_car = add_vehicle(client, model="Nová", purchase_date="2026-01-05", purchase_odometer="0",
                          sale_date="2026-06-01", sale_odometer="12000")
    add_fuel(client, new_car, date(2026, 3, 10), 5000, "40")
    stats = StatsService(db)
    points = stats.odometer_charts(new_car)["odometer"]
    assert [(p["x"], p["y"], p.get("label")) for p in points] == [
        ("2026-01-05", 0, "Nákup vozidla"), ("2026-03-10", 5000, None), ("2026-06-01", 12000, "Prodej vozidla")]

    blank = add_vehicle(client, model="Bez km", purchase_date="2026-01-05", purchase_odometer="")
    add_fuel(client, blank, date(2026, 3, 10), 80000, "40")
    assert db.get(Vehicle, blank).purchase_odometer is None
    assert [p["x"] for p in stats.odometer_charts(blank)["odometer"]] == ["2026-03-10"]
    import re
    def form_value(vid):
        html = client.get(f"/vehicles/{vid}/edit").text
        return re.search(r'name="purchase_odometer"[^>]*value="([^"]*)"', html).group(1)
    assert form_value(blank) == "" and form_value(new_car) == "0"

    # graf všech vozidel: od nuly i skutečný stav, nákup s popiskem
    series = stats._distance_series([db.get(Vehicle, new_car)])
    first = list(series.values())[0][0]
    assert first == {"x": "2026-01-05", "y": 0, "odo": 0, "label": "Nákup vozidla"}
    assert list(series.values())[0][-1]["odo"] == 12000
