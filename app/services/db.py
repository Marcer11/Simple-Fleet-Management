from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.config import get_database_url


def make_engine(url):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # pool_pre_ping/pool_recycle: vzdálená MySQL zavírá neaktivní spojení
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


DATABASE_URL = get_database_url()

engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
