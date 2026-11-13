from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InterviewCreate(BaseModel):
    application_id: str
    panel_id: str | None = None
    interview_round: str = "Round 1"
    start_time: datetime
    end_time: datetime
    status: str = "Scheduled"
    location: str | None = None


class InterviewRead(InterviewCreate):
    id: str
