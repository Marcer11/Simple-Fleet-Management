"""Palivo a alternativní palivo vozidla: formulář, nabídka při tankování, API."""
import json
import re

from models import Vehicle
from test_web import register, post, add_vehicle, app, db  # noqa: F401
from test_api import new_key, vehicles_api


def _fuel_options(html):
    return json.loads(re.search(r'id="fuel-options">(.*?)</script>', html, re.S).group(1))["fuels"]


def test_vehicle_fuel_form_and_fuel_offer(app, db):
    client = register(app, "vfuel@example.com")
    lpg = add_vehicle(client, model="Octavia", fuel="Benzín", alt_fuel="LPG")
    diesel = add_vehicle(client, model="Superb", fuel="Nafta")
    unknown = add_vehicle(client, model="Fabia")
    car = db.get(Vehicle, lpg)
    assert (car.fuel, car.alt_fuel, car.fuels) == ("Benzín", "LPG", ["Benzín", "LPG"])
    assert db.get(Vehicle, unknown).fuels == []

    # kontroly
    r = post(client, "/vehicles/add", {"brand": "X", "model": "Y", "fuel": "Benzín", "alt_fuel": "Benzín"})
    assert r.status_code == 400 and "jiné než hlavní" in r.text
    r = post(client, "/vehicles/add", {"brand": "X", "model": "Y", "fuel": "Uhlí"})
    assert r.status_code == 400 and "Neznámý druh paliva" in r.text
    r = post(client, "/vehicles/add", {"brand": "X", "model": "Y", "alt_fuel": "LPG"})
    assert r.status_code == 400 and "hlavní palivo" in r.text

    detail = client.get(f"/vehicles/{lpg}?tab=detail").text
    assert "Benzín + LPG" in detail
    edit = client.get(f"/vehicles/{lpg}/edit").text
    assert '<option value="LPG" selected>' in edit

    # formulář tankování: vozidlo nese své druhy paliva, paliva znají svůj druh
    form = client.get("/fuel-records/add").text
    assert f'value="{lpg}"' in form and 'data-fuels="Benzín|LPG"' in form and 'data-fuels="Nafta"' in form
    options = {o["name"]: o["category"] for o in _fuel_options(form)}
    assert options["Benzín"] == "Benzín" and options["LPG"] == "LPG"
    # bez tankování se předvyplní první palivo druhu vozidla
    assert re.search(rf'value="{diesel}"[^>]*data-fuel="Nafta"', form)
    assert not re.search(rf'value="{unknown}"[^>]*data-fuel=', form)


def test_vehicle_fuel_in_api(app):
    client = register(app, "vfuelapi@example.com")
    key = new_key(client)
    add_vehicle(client, model="Octavia", license_plate="1AB2345", fuel="Benzín", alt_fuel="CNG")
    add_vehicle(client, model="Fabia", license_plate="2AB2345")
    items = {v["plate"]: v for v in vehicles_api(app, key).json()["vehicles"]}
    assert (items["1AB2345"]["fuel"], items["1AB2345"]["alt_fuel"]) == ("Benzín", "CNG")
    assert (items["2AB2345"]["fuel"], items["2AB2345"]["alt_fuel"]) == (None, None)
