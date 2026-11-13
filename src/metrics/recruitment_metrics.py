from __future__ import annotations


def safe_divide(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def calculate_metrics(dataset: dict[str, object]) -> dict[str, float]:
    requisitions = len(dataset.get("requisitions", []))
    candidates = len(dataset.get("candidates", []))
    applications = len(dataset.get("applications", []))
    interviews = len(dataset.get("interviews", []))
    offers = len(dataset.get("offers", []))
    return {
        "total_requisitions": requisitions,
        "total_candidates": candidates,
        "total_applications": applications,
        "applications_by_stage": len(dataset.get("applications", [])),
        "application_conversion_rate": safe_divide(applications, max(requisitions, 1)),
        "interview_conversion_rate": safe_divide(interviews, max(applications, 1)),
        "offer_acceptance_rate": safe_divide(offers, max(applications, 1)),
        "candidate_selection_rate": safe_divide(offers, max(candidates, 1)),
    }
