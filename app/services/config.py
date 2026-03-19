import os
from dotenv import load_dotenv

load_dotenv()


DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = os.getenv("DB_PORT", "3306")


def validate_config():
    missing = []

    if not DB_HOST:
        missing.append("DB_HOST")
    if not DB_USER:
        missing.append("DB_USER")
    if not DB_PASSWORD:
        missing.append("DB_PASSWORD")
    if not DB_NAME:
        missing.append("DB_NAME")

    if missing:
        raise ValueError(f"Chybí proměnné v .env: {', '.join(missing)}")