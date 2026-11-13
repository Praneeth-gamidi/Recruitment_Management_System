from __future__ import annotations

from pydantic import BaseModel


class CandidateCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    location: str | None = None
    education: str | None = None
    experience_years: int = 0


class CandidateRead(CandidateCreate):
    id: str
