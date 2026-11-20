import os
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

# Testy běží proti SQLite v paměti - nikdy ne proti DB z .env
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ALLOW_REGISTRATION"] = "true"

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import services.security as security  # noqa: E402
from models import Base  # noqa: E402

security.ITERATIONS = 1_000  # rychlé hashování hesel v testech


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Testy nesmí volat ČNB - kurz se podvrhne."""
    from decimal import Decimal
    import services.pricing as pricing

    def fake_rate(currency_code, on_date):
        return {"EUR": Decimal("25"), "PLN": Decimal("5.8")}.get(currency_code.upper(), Decimal("1"))

    monkeypatch.setattr(pricing, "get_rate", fake_rate)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def users(session):
    from services.user_service import UserService
    service = UserService(session)
    return {
        "alice": service.create_user("alice@example.com", "Alice", "heslo1234"),
        "bob": service.create_user("bob@example.com", "Bob", "heslo1234"),
        "carol": service.create_user("carol@example.com", "Carol", "heslo1234"),
    }
