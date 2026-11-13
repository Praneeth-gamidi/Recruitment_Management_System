from __future__ import annotations

DEFAULT_THRESHOLDS = {
    "Strong Hire": (4.0, 5.0),
    "Hire / Further Review": (3.0, 3.99),
    "Borderline": (2.0, 2.99),
    "No Hire": (0.0, 1.99),
}


def weighted_score(rating_map: dict[str, tuple[float, float]], weights: dict[str, float] | None = None) -> float:
    weights = weights or {name: 1.0 for name in rating_map}
    total_weight = sum(weights.get(k, 1.0) for k in rating_map)
    if total_weight == 0:
        return 0.0
    return sum(weights.get(k, 1.0) * rating for k, (rating, _) in rating_map.items()) / total_weight


def recommendation_for_score(score: float) -> str:
    for label, (lower, upper) in DEFAULT_THRESHOLDS.items():
        if lower <= score <= upper:
            return label
    return "No Hire"
