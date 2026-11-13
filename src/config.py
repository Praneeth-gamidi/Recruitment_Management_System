from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

_database_url = os.getenv("DATABASE_URL")
if _database_url:
    DATABASE_URL = _database_url
else:
    _db_user = os.getenv("DB_USER")
    _db_password = os.getenv("DB_PASSWORD")
    if not _db_user or not _db_password:
        raise RuntimeError("Set DATABASE_URL or both DB_USER and DB_PASSWORD in the environment.")
    DATABASE_URL = URL.create(
        "postgresql+psycopg2",
        username=_db_user,
        password=_db_password,
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "recruitment_db"),
    )

SQLITE_URL = URL.create("sqlite", database=str(ROOT_DIR / "recruitment.db"))

DEFAULT_SEED = 20261022
