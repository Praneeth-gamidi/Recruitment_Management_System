from __future__ import annotations


def generate_offers(applications: list[dict]) -> list[dict]:
    offers = []
    for idx, application in enumerate(applications[:5], start=1):
        offers.append({
            "id": f"OFF-{idx:06d}",
            "application_id": application["candidate_id"],
            "proposed_salary": 150000,
            "approved_salary": 150000,
            "currency": "USD",
            "status": "Pending",
        })
    return offers
