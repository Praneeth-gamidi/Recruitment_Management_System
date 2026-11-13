from __future__ import annotations

from src.database.connection import get_engine


def test_engine_creates_sqlite_database() -> None:
    engine = get_engine(use_sqlite=True)
    assert engine is not None
