from __future__ import annotations

from src.business_rules.evaluation_rules import recommendation_for_score, weighted_score


def test_weighted_score_matches_formula() -> None:
    scores = {"Python": (4.0, 1.0), "SQL": (5.0, 1.0)}
    assert weighted_score(scores) == 4.5


def test_recommendation_thresholds() -> None:
    assert recommendation_for_score(4.5) == "Strong Hire"
