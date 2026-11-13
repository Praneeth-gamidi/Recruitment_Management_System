from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/")
def analytics() -> dict:
    return {"message": "Analytics API"}
