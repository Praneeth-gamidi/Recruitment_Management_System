from __future__ import annotations

from datetime import datetime


def _pad(value: int, width: int = 6) -> str:
    return str(value).zfill(width)


def generate_requisition_id(year: int | None = None, counter: int | None = None) -> str:
    year = year or datetime.now().year
    counter = counter if counter is not None else 1
    return f"REQ-{year}-{_pad(counter, 6)}"


def generate_candidate_id(counter: int | None = None) -> str:
    counter = counter if counter is not None else 1
    return f"CAND-{_pad(counter, 6)}"


def generate_application_id(candidate_id: str, requisition_id: str) -> str:
    return f"APP-{candidate_id}-{requisition_id}"


def generate_interview_id(year: int | None = None, counter: int | None = None) -> str:
    year = year or datetime.now().year
    counter = counter if counter is not None else 1
    return f"INT-{year}-{_pad(counter, 6)}"


def generate_scorecard_id(interview_id: str, revision: int | None = None) -> str:
    revision = revision if revision is not None else 1
    return f"SCORE-{interview_id}-REV-{_pad(revision, 6)}"


def generate_offer_id(year: int | None = None, counter: int | None = None) -> str:
    year = year or datetime.now().year
    counter = counter if counter is not None else 1
    return f"OFF-{year}-{_pad(counter, 6)}"


def generate_approval_id(counter: int | None = None) -> str:
    counter = counter if counter is not None else 1
    return f"APPROVAL-{_pad(counter, 6)}"


def generate_event_id(counter: int | None = None) -> str:
    counter = counter if counter is not None else 1
    return f"EVT-{_pad(counter, 6)}"
