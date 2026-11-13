from __future__ import annotations

from src.business_rules.stage_transitions import is_valid_transition


def test_valid_transition() -> None:
    assert is_valid_transition("Applied", "Screening") is True


def test_invalid_transition() -> None:
    assert is_valid_transition("Applied", "Hired") is False
