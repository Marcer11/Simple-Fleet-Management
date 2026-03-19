from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT, validate_config

validate_config()

DATABASE_URL = (
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)