from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.logging import LOGGER_NAME
from src.database.session import get_db

logger = logging.getLogger(LOGGER_NAME)
router = APIRouter(tags=["system"])


@router.get("/", include_in_schema=False)
def root(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "status": "ok",
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@router.get("/health/db")
def database_health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database health check failed", exc_info=exc)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "database_unavailable",
                "message": "Database health check failed.",
            },
        ) from exc
    return {"status": "healthy", "database": "connected"}
