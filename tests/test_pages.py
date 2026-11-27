"""Struktura stránek: záložky vozidla, detail pneumatiky, místa, nastavení a přidávání záznamů."""
from datetime import date, timedelta

from models import Expense, Tire
from test_tires import add_tire, swap
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401


def test_vehicle_tabs(app, db):
    client = register(app, "tabs@example.com")
    car = add_vehicle(client, model="Octavia")
    today = date.today()
    add_fuel(client, car, today - timedelta(days=20), 10000, "40", station_name="MOL Brno",
             station_address="Vídeňská 5, Brno")
    add_fuel(client, car, today - timedelta(days=10), 10500, "35", station_name="MOL Brno",
             station_address="Vídeňská 5, Brno")
    assert post(client, "/services/add", {"vehicle_id": car, "service_date": (today - timedelta(days=5)).isoformat(),
                                          "odometer": 10600, "st:Výměna oleje": "on", "place": "Autoservis Novák",
                                          "price_paid": "2500", "currency_code": "CZK"}).status_code == 303
    assert post(client, "/expenses/add", {"vehicle_id": car, "expense_date": today.isoformat(), "category": "Mytí",
                                          "place": "Myčka Kaufland", "price_paid": "150",
                                          "currency_code": "CZK"}).status_code == 303
    assert db.query(Expense).one().place == "Myčka Kaufland"
    post(client, "/notes/add", {"vehicle_id": car, "note_date": today.isoformat(), "note_time": "08:00",
                                "category": "Garáž", "text": "zimní garáž"})

    overview = client.get(f"/vehicles/{car}").text
    for tab in ("Přehled", "Údaje", "Tankování", "Servis", "Výdaje", "Poznámky", "Pneumatiky", "Statistiky"):
        assert f">{tab}</a>" in overview, tab
    assert 'class="active" aria-current="page">Přehled' in overview
    assert "Časová osa" in overview and "summary-card" in overview and "Autoservis Novák" in overview
    assert "‹ Vozidla" in overview and "Zapsat" in overview and "Nepojízdné" in overview  # nabídka zápisu

    fuel = client.get(f"/vehicles/{car}?tab=fuel").text
    assert "Všechna tankování" in fuel and "/places/station?key=v%C3%ADde%C5%88sk%C3%A1+5%2C+brno" in fuel
    service = client.get(f"/vehicles/{car}?tab=service").text
    assert "Historie servisu" in service and "Výměna oleje" in service and "Pravidelný servis" in service
    expenses = client.get(f"/vehicles/{car}?tab=expenses").text
    assert "Myčka Kaufland" in expenses and "Všechny výdaje" in expenses
    notes = client.get(f"/vehicles/{car}?tab=notes").text
    assert "zimní garáž" in notes and "Garáž" in notes
    assert "Na voze" in client.get(f"/vehicles/{car}?tab=tires").text
    assert "Správa vozidla" in client.get(f"/vehicles/{car}?tab=detail").text
    stats = client.get(f"/vehicles/{car}/stats").text
    assert 'class="active" aria-current="page">Statistiky' in stats
    # neznámá záložka = přehled
    assert "summary-card" in client.get(f"/vehicles/{car}?tab=nic").text


def test_places(app, db):
    client = register(app, "places@example.com")
    car = add_vehicle(client, model="Octavia")
    other = add_vehicle(client, model="Fabia")
    today = date.today()
    for vid, days, km in ((car, 300, 1000), (car, 30, 2000), (other, 20, 5000)):
        assert post(client, "/services/add", {"vehicle_id": vid, "service_date": (today - timedelta(days=days)).isoformat(),
                                              "odometer": km, "st:STK": "on", "place": " autoservis  Novák ",
                                              "price_paid": "1000", "currency_code": "CZK"}).status_code == 303
    add_fuel(client, car, today - timedelta(days=5), 3000, "40", unit_price="40", station_name="Shell D1",
             station_address="D1 km 21")

    page = client.get("/places").text
    assert "Servisy" in page and "Čerpací stanice" in page and "Místa výdajů" in page
    assert "autoservis Novák" in page and "/places/service?key=autoservis+nov%C3%A1k" in page

    detail = client.get("/places/service?key=autoservis+nov%C3%A1k").text.replace("\xa0", " ")
    assert "‹ Servisy" in detail and "3 000 Kč" in detail
    assert "Škoda Octavia" in detail and "Škoda Fabia" in detail and "Po letech" in detail

    stations = client.get("/places?kind=station").text
    assert "Shell" in stations and "D1 km 21" in stations
    station = client.get("/places/station?key=d1+km+21").text.replace("\xa0", " ")
    assert "Shell D1" in station and "40,00" in station and "40 l" in station
    # stará adresa přehledu pump přesměruje
    r = client.get("/fuel-records/stations?all=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/places?kind=station&all=1"
    assert client.get("/places/service?key=neexistuje").status_code == 404
    assert client.get("/places/nic?key=x").status_code == 404
    # cizí vozidla nejsou vidět
    stranger = register(app, "cizi@example.com")
    assert stranger.get("/places/service?key=autoservis+nov%C3%A1k").status_code == 404


def test_tire_detail_is_read_only(app, db):
    client = register(app, "tiredetail@example.com")
    car = add_vehicle(client, model="Octavia")
    tire = add_tire(client, db)
    swap(client, car, date.today() - timedelta(days=10), 1000, [(tire, "all")])
    page = client.get(f"/tires/{tire.id}").text
    assert "Historie nasazení" in page and "Údaje" in page and "‹ Pneumatiky" in page
    assert 'name="manufacturer"' not in page  # žádný formulář
    assert f'href="/tires/{tire.id}/edit"' in page
    edit = client.get(f"/tires/{tire.id}/edit").text
    assert 'name="manufacturer"' in edit and "Historie nasazení" not in edit
    # seznam vede na detail
    assert f'href="/tires/{tire.id}"' in client.get("/tires").text
    r = post(client, f"/tires/{tire.id}/edit", {"season": "Letní", "manufacturer": "Michelin", "quantity": "4",
                                                "currency_code": "CZK"})
    assert r.status_code == 303 and r.headers["location"] == f"/tires/{tire.id}"
    assert db.query(Tire).count() == 1


def test_settings_and_add_menu(app, db):
    client = register(app, "settings@example.com")
    add_vehicle(client)
    for url, active in (("/profile", "Účet"), ("/fuel-types", "Paliva"), ("/service-intervals", "Servisní intervaly")):
        page = client.get(url).text
        assert "<h1>Nastavení</h1>" in page and f'aria-current="page">{active}</a>' in page, url
        assert 'class="settings-link active"' in page
    fuel = client.get("/fuel-records").text
    assert 'href="/fuel-types"' not in fuel  # paliva jsou v nastavení
    home = client.get("/").text
    assert "Nový záznam" in home and 'data-menu' in home and "/tire-swaps/add" in home
    assert 'href="/places"' in home  # položka menu


def test_records_open_read_only(app, db):
    from models import FuelRecord, ServiceRecord, VehicleNote
    client = register(app, "readonly@example.com")
    car = add_vehicle(client, model="Octavia")
    today = date.today()
    add_fuel(client, car, today - timedelta(days=3), 1000, "40", station_name="MOL Brno")
    post(client, "/services/add", {"vehicle_id": car, "service_date": today.isoformat(), "odometer": 1100,
                                   "st:STK": "on", "place": "STK Brno", "price_paid": "1800", "currency_code": "CZK"})
    post(client, "/notes/add", {"vehicle_id": car, "note_date": today.isoformat(), "note_time": "09:00",
                                "category": "Garáž", "text": "zimní garáž"})
    fuel = db.query(FuelRecord).one()
    service = db.query(ServiceRecord).one()
    note = db.query(VehicleNote).one()

    # seznamy, časová osa a místa vedou na detail, ne na úpravu
    assert f'href="/fuel-records/{fuel.id}"' in client.get("/fuel-records").text
    assert f"/fuel-records/{fuel.id}/edit" not in client.get("/fuel-records").text
    timeline = client.get(f"/vehicles/{car}").text
    assert f'href="/services/{service.id}"' in timeline and f"/services/{service.id}/edit" not in timeline
    assert f'href="/services/{service.id}"' in client.get("/places/service?key=stk+brno").text

    for url, text in ((f"/fuel-records/{fuel.id}", "MOL Brno"), (f"/services/{service.id}", "STK Brno"),
                      (f"/notes/{note.id}", "zimní garáž")):
        page = client.get(url).text
        assert text in page and "Správa záznamu" in page, url
        assert '<form method="post" class="card">' not in page  # žádný formulář
        assert f'{url}/edit"' in page and f'{url}/delete"' in page
    # formulář úpravy už mazání nenabízí (je v detailu)
    assert f"/fuel-records/{fuel.id}/delete" not in client.get(f"/fuel-records/{fuel.id}/edit").text
    assert f"/services/{service.id}/delete" not in client.get(f"/services/{service.id}/edit").text

    # sdílené jen pro čtení: detail ano, úpravy ne
    viewer = register(app, "viewer@example.com")
    post(client, f"/vehicles/{car}/sharing", {"action": "add", "email": "viewer@example.com", "role": "viewer"})
    page = viewer.get(f"/fuel-records/{fuel.id}").text
    assert "MOL Brno" in page and "Správa záznamu" not in page
    assert register(app, "cizi2@example.com").get(f"/fuel-records/{fuel.id}").status_code in (403, 404)
    # ostatní cesty pod stejnou adresou fungují dál
    assert client.get("/fuel-records/export.csv?all=1").status_code == 200
    assert client.get("/services/export.csv?all=1").status_code == 200


def test_tire_records_and_manage(app, db):
    from models import TireSwap
    client = register(app, "tiremanage@example.com")
    car = add_vehicle(client, model="Octavia")
    tire = add_tire(client, db)
    swap(client, car, date.today() - timedelta(days=10), 1000, [(tire, "all")])
    s = db.query(TireSwap).one()
    page = client.get(f"/tire-swaps/{s.id}").text
    assert "Nasazeno" in page and "Letní Michelin Primacy 4" in page and f"/tire-swaps/{s.id}/edit" in page
    detail = client.get(f"/tires/{tire.id}").text
    # úprava jen jednou, dole ve Správě pneumatiky
    assert detail.count(f'href="/tires/{tire.id}/edit"') == 1
    assert detail.index("Správa pneumatiky") < detail.index(f'href="/tires/{tire.id}/edit"')
    assert f"/tires/{tire.id}/delete" in detail and f"/tires/{tire.id}/delete" not in client.get(f"/tires/{tire.id}/edit").text
    vehicle = client.get(f"/vehicles/{car}?tab=detail").text
    assert vehicle.count(f'href="/vehicles/{car}/edit"') == 1
    assert vehicle.index("Správa vozidla") < vehicle.index(f'href="/vehicles/{car}/edit"')
    assert f'href="/vehicles/{car}/edit"' not in client.get(f"/vehicles/{car}").text


def test_stats_insights_and_dashboard(app, db):
    client = register(app, "insights@example.com")
    car = add_vehicle(client, model="Octavia")
    today = date.today()
    add_fuel(client, car, today - timedelta(days=400), 1000, "40", unit_price="35", station_name="Shell D1")
    add_fuel(client, car, today - timedelta(days=20), 9000, "45", unit_price="38", station_name="MOL Brno")
    post(client, "/services/add", {"vehicle_id": car, "service_date": (today - timedelta(days=10)).isoformat(),
                                   "odometer": 9100, "st:Výměna oleje": "on", "st:Brzdy": "on",
                                   "place": "Autoservis Novák", "price_paid": "4000", "currency_code": "CZK"})
    page = client.get("/stats?period=all").text.replace("\xa0", " ")
    for text in ("Po letech", "Kam jdou peníze", "Servis podle typu", "Nejlevnější palivo", "Nejčastější pumpy",
                 "Autoservis Novák"):
        assert text in page, text
    assert "2 000 Kč" in page  # servis se dvěma položkami: cena napůl
    assert "Po letech" in client.get(f"/vehicles/{car}/stats?period=all").text
    home = client.get("/").text
    assert f"Ujeto {today.year}" in home and f"Tankování {today.year}" in home


def test_manifest_is_installable(app):
    client = register(app, "pwa@example.com")
    manifest = client.get("/manifest.webmanifest").json()
    assert manifest["id"] == "/" and manifest["display"] == "standalone"
    sizes = {i["sizes"] for i in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes and any(i.get("purpose") == "maskable" for i in manifest["icons"])
    for item in manifest["icons"] + manifest["screenshots"]:
        assert client.get(item["src"]).status_code == 200, item["src"]
    assert {s["form_factor"] for s in manifest["screenshots"]} == {"narrow", "wide"}
    assert len(manifest["shortcuts"]) <= 4
    profile = client.get("/profile").text
    assert "Nainstalovat aplikaci" in profile and 'name="apple-mobile-web-app-capable"' in profile


def test_stations_without_address_and_brands(app, db):
    client = register(app, "brands@example.com")
    car = add_vehicle(client, model="Octavia")
    today = date.today()
    add_fuel(client, car, today - timedelta(days=40), 1000, "40", station_name="MOL")
    add_fuel(client, car, today - timedelta(days=30), 1500, "40", station_name="MOL Brno")
    add_fuel(client, car, today - timedelta(days=20), 2000, "40", station_name="MOL", station_address="Vídeňská 5, Brno")
    add_fuel(client, car, today - timedelta(days=10), 2500, "40", station_name="Benzina Praha",
             station_address="Chodovská 1, Praha")
    page = client.get("/places?kind=station").text
    # MOL: jedna adresa + jedna položka „bez adresy“ (oba názvy pod ní); Benzina zvlášť, ne pod ORLENem
    assert page.count("<em>bez adresy</em>") == 1 and "MOL, MOL Brno" in page
    assert "Benzina" in page and "ORLEN" not in page
    assert "data-collapsible" in page and 'aria-controls="brand-1"' in page and "Rozbalit vše" in page
    detail = client.get("/places/station?key=~mol").text
    assert "MOL – bez adresy" in detail and "zapsáno jako MOL, MOL Brno" in detail
    stats = client.get("/stats?period=all").text
    assert "Nejoblíbenější značky pump" in stats and "Vídeňská 5, Brno" in stats and "MOL – bez adresy" in stats
