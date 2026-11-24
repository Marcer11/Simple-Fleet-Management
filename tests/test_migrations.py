from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from models import Base

ROOT = Path(__file__).resolve().parent.parent


def _upgrade(connection, revision="head"):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, revision)


def _diffs(connection):
    ctx = MigrationContext.configure(connection, opts={"compare_type": False})
    return compare_metadata(ctx, Base.metadata)


def test_fresh_database_matches_models(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    with engine.begin() as conn:
        _upgrade(conn)
    with engine.connect() as conn:
        assert _diffs(conn) == []


# Původní schéma z database.sql (přepsané pro SQLite)
LEGACY_SCHEMA = [
    """CREATE TABLE vehicles (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        brand VARCHAR(50) NOT NULL, model VARCHAR(50) NOT NULL,
        production_year INTEGER, color VARCHAR(30), license_plate VARCHAR(10),
        vin CHAR(17), note TEXT, purchase_date DATE, sale_date DATE,
        is_active BOOLEAN NOT NULL DEFAULT 1, color_hex CHAR(7) NOT NULL DEFAULT '#FFFFFF',
        CONSTRAINT uq_vehicles_license_plate UNIQUE (license_plate),
        CONSTRAINT uq_vehicles_vin UNIQUE (vin))""",
    """CREATE TABLE fuel_records (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER NOT NULL, refuel_datetime DATETIME NOT NULL, odometer INTEGER NOT NULL,
        fuel_type VARCHAR(15) NOT NULL, volume_liters DECIMAL(7,2) NOT NULL, unit_price DECIMAL(10,3),
        price_paid DECIMAL(12,3) NOT NULL, currency_code CHAR(3) NOT NULL DEFAULT 'CZK',
        unit_price_local DECIMAL(10,3), price_local DECIMAL(12,3), payment_method VARCHAR(20),
        station_name VARCHAR(100), full_tank BOOLEAN NOT NULL DEFAULT 0,
        skipped_refuel BOOLEAN NOT NULL DEFAULT 0, consumption DECIMAL(5,2), note TEXT,
        CONSTRAINT fk_fuel_records_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id) ON DELETE CASCADE ON UPDATE CASCADE)""",
    "CREATE INDEX idx_fuel_records_vehicle_id ON fuel_records (vehicle_id)",
    "CREATE INDEX idx_fuel_records_refuel_daterite ON fuel_records (refuel_datetime)",
]


def test_upgrade_existing_database_keeps_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        for statement in LEGACY_SCHEMA:
            conn.execute(text(statement))
        conn.execute(text("INSERT INTO vehicles (brand, model, license_plate) VALUES ('Škoda', 'Fabia', '1A11111')"))
        conn.execute(text(
            "INSERT INTO fuel_records (vehicle_id, refuel_datetime, odometer, fuel_type, volume_liters, price_paid) "
            "VALUES (1, '2026-01-01 10:00:00', 1000, 'Benzín', 40, 1600)"))

    with engine.begin() as conn:
        _upgrade(conn)

    with engine.connect() as conn:
        assert _diffs(conn) == []
        assert conn.execute(text("SELECT COUNT(*) FROM fuel_records")).scalar() == 1
        assert conn.execute(text("SELECT owner_id FROM vehicles")).scalar() is None
        uniques = inspect(conn).get_unique_constraints("vehicles")
        assert uniques == []

    # stejná SPZ už může být u více vozidel (různí uživatelé)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO vehicles (brand, model, license_plate) VALUES ('Škoda', 'Fabia', '1A11111')"))


def test_database_url_with_special_password(monkeypatch):
    """Heslo se speciálními znaky musí projít do ovladače beze změny."""
    from sqlalchemy.engine import make_url
    from services import config

    password = "p@ss%w rd+/:#?&=ž"
    monkeypatch.setattr(config, "DATABASE_URL_OVERRIDE", None)
    monkeypatch.setattr(config, "DB_HOST", "localhost")
    monkeypatch.setattr(config, "DB_USER", "fleet-management")
    monkeypatch.setattr(config, "DB_PASSWORD", password)
    monkeypatch.setattr(config, "DB_NAME", "fleet")
    url = make_url(config.get_database_url())
    assert url.password == password
    assert url.username == "fleet-management" and url.database == "fleet"
    assert url.query["charset"] == "utf8mb4"


def test_alembic_env_uses_url_unchanged(tmp_path):
    """env.py nesmí URL upravovat (dříve zdvojoval % a rozbil tak heslo)."""
    db = tmp_path / "a%b.db"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = f"sqlite:///{db}"
    command.upgrade(cfg, "head")
    assert db.exists()


def test_vehicle_fuel_and_lender_prefilled_from_records(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'prefill.db'}")
    with engine.begin() as conn:
        _upgrade(conn, "0018_engine")
        conn.execute(text("INSERT INTO vehicles (id, brand, model, is_active, color_hex, is_rental) VALUES"
                          " (1, 'Škoda', 'Octavia', 1, '#FFFFFF', 0), (2, 'Toyota', 'Yaris', 1, '#FFFFFF', 1)"))
        for i, (vid, cat) in enumerate([(1, "LPG"), (1, "LPG"), (1, "Benzín"), (1, "LPG"), (2, "Benzín")]):
            conn.execute(text("INSERT INTO fuel_records (vehicle_id, refuel_datetime, odometer, fuel_type,"
                              " fuel_category, volume_liters, price_paid, currency_code, full_tank, skipped_refuel)"
                              " VALUES (:v, :t, :o, :c, :c, 30, 1000, 'CZK', 1, 0)"),
                         {"v": vid, "t": f"2026-01-0{i + 1} 10:00:00", "o": 1000 + i, "c": cat})
        conn.execute(text("INSERT INTO vehicle_rentals (vehicle_id, provider, date_from, currency_code) VALUES"
                          " (2, 'Stará půjčovna', '2026-01-01', 'CZK'), (2, 'AutoPraha', '2026-05-01', 'CZK')"))
        _upgrade(conn)
        rows = conn.execute(text("SELECT id, fuel, alt_fuel, lender FROM vehicles ORDER BY id")).all()
    assert [tuple(r) for r in rows] == [(1, "Benzín", "LPG", None), (2, "Benzín", None, "AutoPraha")]
