from __future__ import annotations


def anomaly_summary(anomalies: list[dict[str, str]]) -> dict[str, int]:
    categories = {
        "missing_required_review": "MISSING_REQUIRED_REVIEW",
        "double_booking": "DOUBLE_BOOKING",
        "offer_outside_band": "OFFER_OUTSIDE_BAND",
        "withdrawn_candidate_scheduled": "WITHDRAWN_CANDIDATE_SCHEDULED",
        "irrelevant_evaluation_criteria": "IRRELEVANT_EVALUATION_CRITERIA",
    }
    summary = {"total": len(anomalies)}
    summary.update(
        {
            output_key: sum(1 for item in anomalies if item.get("issue_type") == issue_type)
            for output_key, issue_type in categories.items()
        }
    )
    return summary
