from __future__ import annotations

STAGE_SEQUENCE = [
    "Applied",
    "Screening",
    "Assessment",
    "Technical Interview",
    "Managerial Interview",
    "HR Interview",
    "Offer",
    "Hired",
]

TERMINAL_STATES = {"Rejected", "Withdrawn"}

TRANSITION_MAP = {
    "Applied": {"Screening", "Rejected", "Withdrawn"},
    "Screening": {"Assessment", "Rejected", "Withdrawn"},
    "Assessment": {"Technical Interview", "Rejected", "Withdrawn"},
    "Technical Interview": {"Managerial Interview", "Rejected", "Withdrawn"},
    "Managerial Interview": {"HR Interview", "Rejected", "Withdrawn"},
    "HR Interview": {"Offer", "Rejected", "Withdrawn"},
    "Offer": {"Hired", "Rejected", "Withdrawn"},
    "Hired": set(),
    "Rejected": set(),
    "Withdrawn": set(),
}


def is_valid_transition(current_stage: str, next_stage: str) -> bool:
    if current_stage == next_stage:
        return True
    if next_stage in TERMINAL_STATES:
        return current_stage in TRANSITION_MAP and next_stage in TRANSITION_MAP[current_stage]
    return next_stage in TRANSITION_MAP.get(current_stage, set())
