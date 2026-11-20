from datetime import date, datetime

import pytest
import requests

from services import config, timeline
from test_web import register, post, add_vehicle, add_fuel, app, db  # noqa: F401

KEY = "tl_" + "a1B2c3D4" * 5


class FakeResponse:
    def __init__(self, status, payload=None, bad_json=False):
        self.status_code = status
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def timeline_api(monkeypatch):
    """Podvržené Timeline API; `calls` zaznamenává dotazy."""
    monkeypatch.setattr(config, "TIMELINE_URL", "http://timeline.test")
    state = {"response": FakeResponse(200, {"found": False}), "calls": []}

    def fake_get(url, params=None, headers=None, timeout=None, allow_redirects=True):
        state["calls"].append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        response = state["response"]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(timeline.requests, "get", fake_get)
    return state


FOUND = {"found": True, "name": "MOL Štěrboholská spojka", "address": "Štěrboholská spojka, 102 00 Praha 10",
         "city": "Praha", "country": "CZ", "type": "Čerpací stanice", "place_id": "x", "lat": None, "lng": None,
         "arrive": "2026-11-20T14:28:00", "leave": "2026-11-20T14:41:00", "minutes_off": 0}


def test_client(timeline_api):
    at = datetime(2026, 11, 20, 14, 35)
    timeline_api["response"] = FakeResponse(200, FOUND)
    stop = timeline.find_fuel_stop(KEY, at)
    assert stop["name"] == "MOL Štěrboholská spojka" and stop["address"].startswith("Štěrboholská")
    call = timeline_api["calls"][0]
    assert call["url"] == "http://timeline.test/api/fuel-stop"
    assert call["params"]["at"] == "2026-11-20T14:35"
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert KEY not in call["url"] and call["timeout"] == 5

    timeline_api["response"] = FakeResponse(200, {"found": False})
    assert timeline.find_fuel_stop(KEY, at) is None

    # prázdná adresa -> město a země
    timeline_api["response"] = FakeResponse(200, {**FOUND, "address": ""})
    assert timeline.find_fuel_stop(KEY, at)["address"] == "Praha, CZ"

    for response, kind in [(FakeResponse(401, {"error": "x"}), "auth"), (FakeResponse(400, {"error": "x"}), "request"),
                           (FakeResponse(500), "unavailable"), (FakeResponse(200, bad_json=True), "unavailable"),
                           (requests.Timeout(), "unavailable"), (requests.ConnectionError(), "unavailable")]:
        timeline_api["response"] = response
        with pytest.raises(timeline.TimelineError) as e:
            timeline.find_fuel_stop(KEY, at)
        assert e.value.kind == kind


def test_disabled_without_url(app, monkeypatch):
    monkeypatch.setattr(config, "TIMELINE_URL", "")
    client = register(app, "t@example.com")
    add_vehicle(client)
    assert "Načíst pumpu" not in client.get("/fuel-records/add").text
    assert "Timeline" not in client.get("/profile").text
    assert client.get("/fuel-records/timeline-stop?date=2026-11-20&time=14:35").json()["status"] == "error"


def test_profile_key_and_lookup(app, db, timeline_api):
    from models import User

    client = register(app, "t@example.com")
    vid = add_vehicle(client)

    # bez klíče: odkaz do profilu místo tlačítka
    form = client.get("/fuel-records/add").text
    assert "Načíst pumpu" not in form and "nastavte API klíč" in form
    assert client.get("/fuel-records/timeline-stop?date=2026-11-20&time=14:35").json()["status"] == "no_key"

    # neplatný tvar klíče
    r = post(client, "/profile", {"action": "timeline", "timeline_api_key": "spatny"})
    assert r.status_code == 400

    assert post(client, "/profile", {"action": "timeline", "timeline_api_key": KEY}).status_code == 303
    assert db.query(User).filter_by(email="t@example.com").one().timeline_api_key == KEY
    profile = client.get("/profile").text
    assert KEY not in profile and KEY[:5] + "…" + KEY[-4:] in profile  # jen maskovaně

    form = client.get("/fuel-records/add").text
    assert "Načíst pumpu" in form and KEY not in form

    timeline_api["response"] = FakeResponse(200, FOUND)
    r = client.get("/fuel-records/timeline-stop?date=2026-11-20&time=14:35")
    data = r.json()
    assert data["status"] == "found" and data["name"] == "MOL Štěrboholská spojka"
    assert r.headers["cache-control"] == "no-store" and KEY not in r.text

    timeline_api["response"] = FakeResponse(200, {"found": False})
    assert client.get("/fuel-records/timeline-stop?date=2026-11-20&time=14:35").json()["status"] == "not_found"

    timeline_api["response"] = FakeResponse(401, {"error": "revoked"})
    data = client.get("/fuel-records/timeline-stop?date=2026-11-20&time=14:35").json()
    assert data["status"] == "no_key" and "profilu" in data["message"]

    assert client.get("/fuel-records/timeline-stop?date=&time=").json()["status"] == "error"

    # adresa stanice se uloží s tankováním
    r = add_fuel(client, vid, date.today(), 1000, "40", station_name="MOL", station_address="Praha 10")
    assert r.status_code == 303
    from models import FuelRecord
    assert db.query(FuelRecord).one().station_address == "Praha 10"

    # odebrání klíče
    assert post(client, "/profile", {"action": "timeline_remove"}).status_code == 303
    db.expire_all()
    assert db.query(User).filter_by(email="t@example.com").one().timeline_api_key is None
