from __future__ import annotations

from src.business_rules.compensation_rules import offer_within_band


def validate_offer(offer_salary: float, min_salary: float, max_salary: float) -> bool:
    return offer_within_band(offer_salary, min_salary, max_salary)
