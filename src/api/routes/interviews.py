from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.get("/")
def list_interviews() -> dict:
    return {"message": "Interviews API"}
