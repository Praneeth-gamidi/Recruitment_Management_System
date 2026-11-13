from __future__ import annotations


def offer_within_band(offer_salary: float, min_salary: float, max_salary: float) -> bool:
    return min_salary <= offer_salary <= max_salary


def out_of_band_offer(offer_salary: float, min_salary: float, max_salary: float, tolerance: float = 0.0) -> bool:
    return not offer_within_band(offer_salary, min_salary, max_salary) and tolerance == 0.0
