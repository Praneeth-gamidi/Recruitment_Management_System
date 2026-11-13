from __future__ import annotations

from collections.abc import Mapping, Set as AbstractSet
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import (
    AuditEvent,
    Interview,
    Interviewer,
    PanelInterviewer,
    Scorecard,
    ScorecardCriteria,
)


def compute_weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    if not scores:
        return 0.0
    numerator = sum(scores.get(key, 0.0) * weights.get(key, 1.0) for key in scores)
    denominator = sum(weights.get(key, 1.0) for key in scores)
    return 0.0 if denominator == 0 else numerator / denominator


def submit_scorecard(
    session: Session,
    scorecard_id: str,
    *,
    reviewer_id: str,
    required_criterion_ids: AbstractSet[str],
    recommendation_thresholds: Mapping[str, Decimal] | None = None,
) -> Scorecard:
    scorecard = session.scalar(
        select(Scorecard).where(Scorecard.scorecard_id == scorecard_id).with_for_update()
    )
    if scorecard is None:
        raise ValueError(f"Scorecard {scorecard_id!r} does not exist.")
    if scorecard.completion_status != "DRAFT":
        raise ValueError("Only draft scorecards can be submitted.")
    if scorecard.reviewer_id != reviewer_id:
        raise ValueError("Only the assigned reviewer may submit this scorecard.")
    if not required_criterion_ids:
        raise ValueError("Scorecard submission requires the applicable rubric criteria.")

    interview = session.scalar(
        select(Interview).where(Interview.interview_id == scorecard.interview_id).with_for_update()
    )
    reviewer = session.scalar(
        select(Interviewer).where(Interviewer.interviewer_id == reviewer_id).with_for_update()
    )
    if interview is None or reviewer is None or reviewer.active_status != "ACTIVE":
        raise ValueError("Scorecard submission requires an existing interview and active reviewer.")
    if interview.status != "COMPLETED":
        raise ValueError("Only completed interviews can receive submitted scorecards.")
    last_date = (interview.end_at - timedelta(microseconds=1)).date()
    membership = session.scalar(
        select(PanelInterviewer)
        .where(
            PanelInterviewer.panel_id == interview.panel_id,
            PanelInterviewer.interviewer_id == reviewer_id,
            PanelInterviewer.effective_from <= interview.start_at.date(),
            (PanelInterviewer.effective_to.is_(None)) | (PanelInterviewer.effective_to >= last_date),
        )
        .with_for_update()
    )
    if membership is None:
        raise ValueError("The reviewer must be an effective member of the interview panel.")

    criteria = list(
        session.scalars(
            select(ScorecardCriteria)
            .where(ScorecardCriteria.scorecard_id == scorecard_id)
            .with_for_update()
        )
    )
    criteria_by_id = {item.criterion_id: item for item in criteria}
    if not required_criterion_ids.issubset(criteria_by_id):
        raise ValueError("Every applicable evaluation criterion must be scored before submission.")
    if any(item.rating > item.maximum_rating_snapshot for item in criteria):
        raise ValueError("A score exceeds its snapshotted rubric maximum.")
    if not criteria:
        raise ValueError("A scorecard must contain at least one evaluation criterion.")

    previous: Scorecard | None = None
    if scorecard.supersedes_scorecard_id is None:
        if scorecard.revision_no != 1:
            raise ValueError("The first scorecard revision must be revision 1.")
    else:
        previous = session.scalar(
            select(Scorecard)
            .where(Scorecard.scorecard_id == scorecard.supersedes_scorecard_id)
            .with_for_update()
        )
        if (
            previous is None
            or previous.interview_id != scorecard.interview_id
            or previous.reviewer_id != reviewer_id
            or previous.completion_status != "SUBMITTED"
        ):
            raise ValueError("A scorecard revision must supersede a submitted card for the same reviewer and interview.")
        latest_revision = session.scalar(
            select(func.max(Scorecard.revision_no)).where(
                Scorecard.interview_id == scorecard.interview_id,
                Scorecard.reviewer_id == reviewer_id,
            )
        )
        if (
            previous.revision_no != scorecard.revision_no - 1
            or scorecard.revision_no != latest_revision
        ):
            raise ValueError("A scorecard revision must be the next revision in its chain.")

    weight_total = sum((item.weight_snapshot for item in criteria), Decimal("0"))
    if weight_total <= 0:
        raise ValueError("Scorecard criterion weights must sum to a positive value.")
    weighted_score = sum(
        (item.weight_snapshot * Decimal(item.rating) for item in criteria),
        Decimal("0"),
    ) / weight_total
    weighted_score = weighted_score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    thresholds = recommendation_thresholds
    if thresholds is None:
        thresholds = {
            "STRONG_HIRE": Decimal("4.00"),
            "HIRE_FURTHER_REVIEW": Decimal("3.00"),
            "BORDERLINE": Decimal("2.00"),
        }
    if set(thresholds) != {"STRONG_HIRE", "HIRE_FURTHER_REVIEW", "BORDERLINE"}:
        raise ValueError("Recommendation policy must define all three score thresholds.")
    if (
        any(value < Decimal("1.00") or value > Decimal("5.00") for value in thresholds.values())
        or thresholds["STRONG_HIRE"] < thresholds["HIRE_FURTHER_REVIEW"]
        or thresholds["HIRE_FURTHER_REVIEW"] < thresholds["BORDERLINE"]
    ):
        raise ValueError("Recommendation thresholds must be ordered within the 1-5 score scale.")
    recommendation = next(
        (
            name
            for name in ("STRONG_HIRE", "HIRE_FURTHER_REVIEW", "BORDERLINE")
            if weighted_score >= thresholds[name]
        ),
        "NO_HIRE",
    )

    now = datetime.now(timezone.utc)
    if previous is not None:
        previous.completion_status = "SUPERSEDED"
        session.add(
            AuditEvent(
                audit_event_id=f"AUDIT-{uuid4().hex}",
                event_type="STATE_CHANGE",
                entity_type="SCORECARD",
                entity_id=previous.scorecard_id,
                related_entity_type="INTERVIEW",
                related_entity_id=interview.interview_id,
                previous_state="SUBMITTED",
                new_state="SUPERSEDED",
                actor_type="USER",
                actor_id=reviewer_id,
                actor_name_snapshot=reviewer.name,
                reason="Superseded by an explicit scorecard revision.",
            )
        )
    scorecard.overall_score = weighted_score
    scorecard.recommendation = recommendation
    scorecard.completion_status = "SUBMITTED"
    scorecard.submitted_at = now
    session.add(
        AuditEvent(
            audit_event_id=f"AUDIT-{uuid4().hex}",
            event_type="STATE_CHANGE",
            entity_type="SCORECARD",
            entity_id=scorecard_id,
            related_entity_type="INTERVIEW",
            related_entity_id=interview.interview_id,
            previous_state="DRAFT",
            new_state="SUBMITTED",
            actor_type="USER",
            actor_id=reviewer_id,
            actor_name_snapshot=reviewer.name,
            reason="Reviewer submitted the completed scorecard.",
        )
    )
    session.flush()
    return scorecard
