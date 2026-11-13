from __future__ import annotations


def generate_scorecards(interviews: list[dict]) -> list[dict]:
    scorecards = []
    for idx, interview in enumerate(interviews, start=1):
        scorecards.append({
            "id": f"SCORE-{interview['id']}-REV-000001",
            "interview_id": interview['id'],
            "reviewer": f"Reviewer {idx}",
            "final_score": 4.0,
            "recommendation": "Strong Hire",
            "completed": True,
            "comments": "Strong candidate",
        })
    return scorecards
