from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class ApplicationCreate(BaseModel):
    candidate_id: str
    requisition_id: str
    application_date: date
    source_channel: str | None = None
    current_stage: str = "Applied"
    status: str = "Applied"


class ApplicationRead(ApplicationCreate):
    id: str
