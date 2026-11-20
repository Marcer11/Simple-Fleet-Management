from datetime import date, datetime
from decimal import Decimal

import pytest

from models import FuelRecord
from services.errors import ValidationError, NotFoundError, PermissionDeniedError
from services.fuel_record_service import FuelRecordService
from services.maintenance_service import (
    ServiceIntervalService, ServiceRecordService, ReminderService, ExpenseService,
    add_months, collect_alerts, LEVEL_OK, LEVEL_WARNING, LEVEL_OVERDUE,
)
from services.pricing import fuel_prices
from services.stats_service import StatsService
from services.user_service import UserService
from services.vehicle_service import VehicleService


def add_fuel(session, vehicle_id, day, odometer, volume, full=True, skipped=False, fuel_type="Benzín", price=40):
    return FuelRecordService(session).create_fuel_record(
        vehicle_id=vehicle_id, refuel_datetime=datetime(2026, 1, day, 12, 0), odometer=odometer,
        fuel_type=fuel_type, volume_liters=volume, unit_price=price, price_paid=price * volume,
        currency_code="CZK", unit_price_local=price, price_local=price * volume,
        full_tank=full, skipped_refuel=skipped,
    )


@pytest.fixture
def car(session, users):
    return VehicleService(session).create_vehicle("Škoda", "Octavia", "1a2 3456", owner_id=users["alice"].id)


# ---------------------------------------------------------------- uživatelé

def test_user_authentication(session, users):
    service = UserService(session)
    assert service.authenticate("ALICE@example.com ", "heslo1234").id == users["alice"].id
    assert service.authenticate("alice@example.com", "spatne") is None
    with pytest.raises(ValidationError):
        service.create_user("alice@example.com", "Alice 2", "heslo1234")
    with pytest.raises(ValidationError):
        service.create_user("new@example.com", "New", "kratke")


# ---------------------------------------------------------------- vozidla

def test_vehicle_validation_and_clearing(session, car):
    service = VehicleService(session)
    assert car.license_plate == "1A23456"
    # pole jde vymazat (dříve nešlo - None znamenalo "beze změny")
    service.update_vehicle(car, {"license_plate": None, "color": None})
    assert car.license_plate is None
    with pytest.raises(ValidationError):
        service.update_vehicle(car, {"vin": "KRATKY"})
    with pytest.raises(ValidationError):
        service.update_vehicle(car, {"color_hex": "red"})
    with pytest.raises(ValidationError):
        service.update_vehicle(car, {"purchase_date": date(2024, 5, 1), "sale_date": date(2023, 1, 1)})


def test_same_plate_allowed_for_different_users(session, users, car):
    other = VehicleService(session).create_vehicle("Škoda", "Octavia", "1A2 3456", owner_id=users["bob"].id)
    assert other.id != car.id


def test_cli_edit_vehicle_keeps_values(session, car):
    VehicleService(session).edit_vehicle(car.id, brand="Skoda")
    assert car.brand == "Skoda" and car.model == "Octavia" and car.license_plate == "1A23456"


def test_sharing_and_permissions(session, users, car):
    service = VehicleService(session)
    alice, bob, carol = users["alice"], users["bob"], users["carol"]

    assert service.get_vehicle_for_user(car.id, alice, "owner") is car
    with pytest.raises(NotFoundError):
        service.get_vehicle_for_user(car.id, bob)

    share = service.share_vehicle(car, "BOB@example.com", "viewer")
    assert service.get_vehicle_for_user(car.id, bob) is car
    with pytest.raises(PermissionDeniedError):
        service.get_vehicle_for_user(car.id, bob, "editor")

    service.update_share_role(car, share.id, "editor")
    assert service.get_vehicle_for_user(car.id, bob, "editor") is car
    assert [v.id for v in service.get_vehicles_for_user(bob)] == [car.id]
    assert service.get_vehicles_for_user(carol) == []

    with pytest.raises(ValidationError):
        service.share_vehicle(car, "nikdo@example.com")
    with pytest.raises(ValidationError):
        service.share_vehicle(car, "alice@example.com")

    service.transfer_ownership(car, share.id)
    assert car.owner_id == bob.id
    assert service.get_role(car, alice) == "editor"

    service.leave_vehicle(car, alice)
    assert service.get_role(car, alice) is None


# ---------------------------------------------------------------- tankování

def test_consumption_full_to_full(session, car):
    add_fuel(session, car.id, 1, 1000, 40)                 # první plná - výchozí bod
    add_fuel(session, car.id, 5, 1300, 10, full=False)     # částečné
    r3 = add_fuel(session, car.id, 10, 1600, 26)           # (10+26)/600*100 = 6.00
    r4 = add_fuel(session, car.id, 15, 2000, 30, skipped=True)  # vynechané -> nepočítá se
    r5 = add_fuel(session, car.id, 20, 2500, 35)           # 35/500*100 = 7.00
    assert r3.consumption == Decimal("6.00")
    assert r4.consumption is None
    assert r5.consumption == Decimal("7.00")

    avg = StatsService(session).avg_consumption(car.id)["Benzín"]["value"]
    assert round(avg, 2) == Decimal("6.45")  # (36+35)/(600+500)*100


def test_consumption_recalculated_after_delete(session, car):
    add_fuel(session, car.id, 1, 1000, 40)
    middle = add_fuel(session, car.id, 5, 1500, 30)
    last = add_fuel(session, car.id, 10, 2000, 35)
    assert last.consumption == Decimal("7.00")
    FuelRecordService(session).delete_fuel_record(middle)
    session.refresh(last)
    assert last.consumption == Decimal("3.50")  # 35 l / 1000 km (smazané tankování v úseku chybí)


def test_consumption_per_fuel_type(session, car):
    add_fuel(session, car.id, 1, 1000, 40, fuel_type="LPG")
    add_fuel(session, car.id, 2, 1010, 5, fuel_type="Benzín")
    lpg = add_fuel(session, car.id, 5, 1500, 50, fuel_type="LPG")
    assert lpg.consumption == Decimal("10.00")


def test_odometer_must_follow_chronology(session, car):
    add_fuel(session, car.id, 1, 1000, 40)
    add_fuel(session, car.id, 10, 2000, 40)
    with pytest.raises(ValidationError):
        add_fuel(session, car.id, 5, 900, 10)
    with pytest.raises(ValidationError):
        add_fuel(session, car.id, 5, 2100, 10)
    add_fuel(session, car.id, 5, 1500, 10)


def test_fuel_prices_foreign_currency():
    prices = fuel_prices("40", "1,5", None, "eur", date(2026, 1, 5))
    assert prices["price_paid"] == Decimal("60.000")
    assert prices["price_local"] == Decimal("1500.000")
    assert prices["currency_code"] == "EUR"
    prices = fuel_prices("40", None, "1500", "CZK", date(2026, 1, 5))
    assert prices["unit_price"] == Decimal("37.500")
    manual = fuel_prices("10", "2", None, "EUR", date(2026, 1, 5), manual_rate="24,5")
    assert manual["price_local"] == Decimal("490.000")
    with pytest.raises(ValidationError):
        fuel_prices("10", None, None, "CZK", date(2026, 1, 5))


def test_exchange_rate_failure_requires_manual_rate(monkeypatch):
    import services.pricing as pricing
    from services.exchange_rate import ExchangeRateError

    def failing(*_):
        raise ExchangeRateError("ČNB nedostupná.")

    monkeypatch.setattr(pricing, "get_rate", failing)
    with pytest.raises(ValidationError, match="ručně"):
        fuel_prices("10", "2", None, "EUR", date(2026, 1, 5))


# ---------------------------------------------------------------- servis a upomínky

def test_add_months():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_service_interval_status(session, car):
    interval_service = ServiceIntervalService(session)
    interval = interval_service.create(vehicle_id=car.id, service_type="Výměna oleje",
                                       interval_months=12, interval_km=15000)
    ServiceRecordService(session).create(vehicle_id=car.id, service_date=date(2026, 1, 1), odometer=10000,
                                         service_type="výměna oleje", price_paid="2500", currency_code="CZK")

    ok = interval_service.get_status(interval, 12000, today=date(2026, 6, 1))
    assert ok.level == LEVEL_OK and ok.due_km == 25000 and ok.due_date == date(2027, 1, 1)

    warn_km = interval_service.get_status(interval, 24000, today=date(2026, 6, 1))
    assert warn_km.level == LEVEL_WARNING and warn_km.km_left == 1000

    warn_date = interval_service.get_status(interval, 12000, today=date(2026, 12, 20))
    assert warn_date.level == LEVEL_WARNING

    overdue = interval_service.get_status(interval, 26000, today=date(2026, 6, 1))
    assert overdue.level == LEVEL_OVERDUE


def test_reminder_repeat(session, car):
    service = ReminderService(session)
    reminder = service.create(vehicle_id=car.id, title="Pojištění", due_date=date(2026, 3, 1), repeat="yearly")
    assert service.get_status(reminder, None, today=date(2026, 2, 20)).level == LEVEL_WARNING
    assert service.get_status(reminder, None, today=date(2026, 1, 1)).level == LEVEL_OK
    service.complete(reminder, today=date(2026, 3, 2))
    assert reminder.due_date == date(2027, 3, 1) and not reminder.is_done

    once = service.create(vehicle_id=car.id, title="Zimní pneu", due_odometer=5000, notify_km_before=300)
    assert service.get_status(once, 4800, today=date(2026, 1, 1)).level == LEVEL_WARNING
    service.complete(once)
    assert once.is_done

    with pytest.raises(ValidationError):
        service.create(vehicle_id=car.id, title="Nic")


def test_alerts_and_stats(session, car):
    add_fuel(session, car.id, 1, 1000, 40)
    add_fuel(session, car.id, 10, 1500, 30)
    ReminderService(session).create(vehicle_id=car.id, title="STK", due_date=date(2026, 1, 5))
    ExpenseService(session).create(vehicle_id=car.id, expense_date=date(2026, 1, 3), category="Mytí",
                                   price_paid="10", currency_code="EUR")
    alerts = collect_alerts(session, [car], today=date(2026, 1, 10))
    assert len(alerts) == 1 and alerts[0].status.level == LEVEL_OVERDUE

    summary = StatsService(session).vehicle_summary(car.id)
    assert summary["expense_cost"] == Decimal("250.000")
    assert summary["fuel_cost"] == Decimal("2800.000")
    assert summary["distance"] == 500
    assert summary["charts"]["consumption"]["Benzín"][0]["y"] == 6.0


def test_delete_vehicle_cascades(session, car):
    add_fuel(session, car.id, 1, 1000, 40)
    VehicleService(session).delete_vehicle(car.id)
    assert session.query(FuelRecord).count() == 0
