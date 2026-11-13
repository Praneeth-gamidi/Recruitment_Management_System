from __future__ import annotations

from datetime import datetime

from src.business_rules.scheduling_rules import intervals_overlap


def validate_schedule(start: datetime, end: datetime) -> bool:
    return start < end


def detect_conflicts(scheduled: list[tuple[str, datetime, datetime]]) -> list[str]:
    conflicts: list[str] = []
    for idx, (label_a, a_start, a_end) in enumerate(scheduled):
        for label_b, b_start, b_end in scheduled[idx + 1:]:
            if intervals_overlap(a_start, a_end, b_start, b_end):
                conflicts.append(f"{label_a} overlaps {label_b}")
    return conflicts
