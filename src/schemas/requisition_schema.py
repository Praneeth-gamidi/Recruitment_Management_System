from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class RequisitionCreate(BaseModel):
    title: str
    department: str
    location: str
    employment_type: str = "Full-time"
    status: str = "Open"
    min_salary: float = 0.0
    max_salary: float = 0.0
    currency: str = "USD"
    vacancies: int = 1
    opening_date: date
    closing_date: date | None = None
    hiring_manager_id: str | None = None


class RequisitionRead(RequisitionCreate):
    id: str
