from __future__ import annotations

from datetime import datetime


def intervals_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def has_duplicate_booking(existing_slots: list[tuple[datetime, datetime]], candidate_start: datetime, candidate_end: datetime) -> bool:
    for start, end in existing_slots:
        if intervals_overlap(start, end, candidate_start, candidate_end):
            return True
    return False
