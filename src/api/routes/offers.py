from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/offers", tags=["offers"])


@router.get("/")
def list_offers() -> dict:
    return {"message": "Offers API"}
