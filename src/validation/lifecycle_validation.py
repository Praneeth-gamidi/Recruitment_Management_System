from __future__ import annotations

from src.business_rules.stage_transitions import is_valid_transition


def validate_lifecycle(current_stage: str, next_stage: str) -> bool:
    return is_valid_transition(current_stage, next_stage)
