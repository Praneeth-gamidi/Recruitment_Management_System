from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class OfferCreate(BaseModel):
    application_id: str
    proposed_salary: float
    approved_salary: float | None = None
    currency: str = "USD"
    joining_date: date | None = None
    status: str = "Pending"


class OfferRead(OfferCreate):
    id: str
