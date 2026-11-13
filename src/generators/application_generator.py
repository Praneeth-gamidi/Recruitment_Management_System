from __future__ import annotations

from datetime import date, timedelta


def generate_applications(candidates: list[dict], requisitions: list[dict]) -> list[dict]:
    applications = []
    for candidate in candidates:
        for requisition in requisitions[:2]:
            applications.append({
                "candidate_id": candidate.get("id"),
                "requisition_id": requisition.get("id"),
                "application_date": date.today() - timedelta(days=7),
                "status": "Applied",
                "current_stage": "Applied",
                "source_channel": "Career Site",
            })
    return applications
