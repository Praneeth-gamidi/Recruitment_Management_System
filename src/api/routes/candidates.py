from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("/")
def list_candidates() -> dict:
    return {"message": "Candidate API"}
