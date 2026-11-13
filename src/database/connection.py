from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL

from src.config import DATABASE_URL, SQLITE_URL


def get_engine(use_sqlite: bool = False, *, url: str | URL | None = None) -> Engine:
    if url is not None:
        return create_engine(url, pool_pre_ping=True, future=True)
    url = SQLITE_URL if use_sqlite else DATABASE_URL
    if use_sqlite:
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            future=True,
        )

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10, future=True)
