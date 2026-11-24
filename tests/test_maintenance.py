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
