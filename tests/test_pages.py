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
