from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/")
def list_approvals() -> dict:
    return {"message": "Approvals API"}
