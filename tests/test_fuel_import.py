"""Import tankování z CSV (formát z Excelu)."""
import io
import json
import re
from datetime import datetime
from decimal import Decimal

from models import FuelRecord
from services import fuel_import
from test_web import register, post, add_vehicle, csrf, app, db  # noqa: F401

SAMPLE = """46193;0,731944444444444;36,9;;41,7;400027;Orlen;Natural 95;Karta;
46203;0,897916666666667;40,4;;19,85;400617;MOL;Natural 95;Karta;1
46217;0,78125;38,9;;48,7;400900;Globus;Natural 95;DKV;
"""


def test_parse_sample():
    rows, errors = fuel_import.parse_csv(SAMPLE.encode("utf-8"))
    assert errors == []
    first = rows[0]
    assert first["at"] == datetime(2026, 6, 20, 17, 34)
    assert first["unit_price"] == Decimal("36.9") and first["total_price"] is None
    assert first["volume"] == Decimal("41.7") and first["odometer"] == 400027
    assert first["currency"] == "CZK" and first["station"] == "Orlen" and first["payment"] == "Karta"
    assert first["full_tank"] is True and rows[1]["full_tank"] is False
    assert rows[2]["payment"] == "Tankovací karta" and rows[2]["at"] == datetime(2026, 7, 14, 18, 45)


def test_parse_other_formats_and_errors():
    content = ("datum;čas;cena;měna;množství;tachometr;pumpa;palivo;platba;částečně\n"
               "24. 11. 2025;17:34;1 520,50;EUR;40;1000;Shell;Diesel;Hotově;\n"
               "2025-11-25;8:05;1500;;30;1500;;Diesel;;ano\n"
               "xx;8:05;1500;;30;1500;;Diesel;;\n"
               "26.11.2025;8:05;1500;;;1500;;Diesel;;\n").encode("cp1250")
    rows, errors = fuel_import.parse_csv(content, price_is_total=True)
    assert len(rows) == 2 and len(errors) == 2
    assert "Řádek 4" in errors[0] and "Řádek 5" in errors[1] and "množství" in errors[1]
    assert rows[0]["total_price"] == Decimal("1520.50") and rows[0]["currency"] == "EUR"
    assert rows[0]["payment"] == "Hotovost" and rows[1]["full_tank"] is False and rows[1]["station"] is None


def upload(client, vid, content, price_mode="unit"):
    return client.post("/fuel-records/import",
                       data={"csrf_token": csrf(client, "/profile"), "vehicle_id": str(vid), "price_mode": price_mode},
                       files={"file": ("tankovani.csv", io.BytesIO(content), "text/csv")})


def test_import_flow_with_timeline(app, db, monkeypatch):
    from services import timeline
    client = register(app, "imp@example.com")
    vid = add_vehicle(client)
    # API klíč Timeline + podvržená odpověď (jen pro první tankování)
    from models import User
    user = db.query(User).filter_by(email="imp@example.com").one()
    user.timeline_api_key = "tl_" + "a" * 20
    db.commit()
    monkeypatch.setattr(timeline, "is_enabled", lambda: True)
    calls = []

    def fake_stop(key, at, tolerance=15):
        calls.append(at)
        if at == datetime(2026, 6, 20, 17, 34):
            return {"name": "ORLEN Praha Chodov", "address": "Roztylská 1, Praha"}
        return None
    monkeypatch.setattr(timeline, "find_fuel_stop", fake_stop)

    r = upload(client, vid, SAMPLE.encode("utf-8"))
    assert r.status_code == 200 and "Importovat 3 tankování" in r.text and "ORLEN Praha Chodov" in r.text
    payload = re.search(r'<textarea name="payload" hidden>(.*?)</textarea>', r.text, re.S).group(1)
    import html
    payload = html.unescape(payload)
    assert len(json.loads(payload)) == 3 and len(calls) == 3
    r = post(client, "/fuel-records/import/confirm", {"vehicle_id": vid, "payload": payload})
    assert r.status_code == 303
    records = db.query(FuelRecord).order_by(FuelRecord.refuel_datetime).all()
    assert len(records) == 3
    assert (records[0].station_name, records[0].station_address) == ("ORLEN Praha Chodov", "Roztylská 1, Praha")
    assert (records[1].station_name, records[1].station_address) == ("MOL", None)
    assert records[1].full_tank is False and records[2].payment_method == "Tankovací karta"
    assert records[0].price_local == Decimal("1538.730") and records[0].unit_price == Decimal("36.900")
    # opakovaný import: vše už zapsané
    r = upload(client, vid, SAMPLE.encode("utf-8"))
    assert "už zapsáno" in r.text and "Nic nového k importu" in r.text
    assert "Import CSV" in client.get("/fuel-records").text


def test_import_requires_vehicle_access(app, db):
    alice = register(app, "a-imp@example.com")
    vid = add_vehicle(alice)
    bob = register(app, "b-imp@example.com")
    r = upload(bob, vid, SAMPLE.encode("utf-8"))
    assert r.status_code == 400 and "Vyberte vozidlo" in r.text
    r = post(bob, "/fuel-records/import/confirm", {"vehicle_id": vid, "payload": "[]"})
    assert r.status_code == 303 and db.query(FuelRecord).count() == 0
