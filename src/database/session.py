from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from src.database.connection import get_engine

engine = get_engine()
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
