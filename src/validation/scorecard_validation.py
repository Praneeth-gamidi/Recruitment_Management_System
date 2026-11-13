from __future__ import annotations


def validate_scorecard(scores: dict[str, float], valid_range: tuple[float, float] = (1, 5)) -> list[str]:
    errors: list[str] = []
    for criterion, score in scores.items():
        if score < valid_range[0] or score > valid_range[1]:
            errors.append(f"{criterion} score out of range: {score}")
    return errors
