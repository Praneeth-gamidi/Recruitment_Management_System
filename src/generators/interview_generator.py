from __future__ import annotations

from datetime import datetime, timedelta


def generate_interviews(applications: list[dict], interviewer_count: int = 6) -> list[dict]:
    interviews = []
    for idx, application in enumerate(applications[:10], start=1):
        start = datetime.utcnow() + timedelta(days=idx)
        interviews.append({
            "id": f"INT-{idx:06d}",
            "application_id": application["candidate_id"],
            "panel_id": f"PANEL-{idx % interviewer_count + 1:04d}",
            "interview_round": "Round 1",
            "start_time": start,
            "end_time": start + timedelta(hours=1),
            "status": "Scheduled",
        })
    return interviews
