from __future__ import annotations

from datetime import datetime, timedelta

from src.business_rules.scheduling_rules import intervals_overlap


def test_overlap_detection() -> None:
    start_a = datetime(2026, 1, 1, 9, 0)
    end_a = datetime(2026, 1, 1, 10, 0)
    start_b = datetime(2026, 1, 1, 9, 30)
    end_b = datetime(2026, 1, 1, 10, 30)
    assert intervals_overlap(start_a, end_a, start_b, end_b) is True
