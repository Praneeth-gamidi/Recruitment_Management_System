from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/requisitions", tags=["requisitions"])


@router.get("/")
def list_requisitions() -> dict:
    return {"message": "Recruitment requisitions API"}
