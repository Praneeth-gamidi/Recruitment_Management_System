from __future__ import annotations

from collections.abc import Set as AbstractSet
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import Application, ApplicationStageHistory, AuditEvent, Interview, Offer, Requisition, Scorecard

from src.business_rules.stage_transitions import STAGE_SEQUENCE


def stage_index(stage: str) -> int:
    try:
        return STAGE_SEQUENCE.index(stage)
    except ValueError:
        return -1


def can_advance(current_stage: str, next_stage: str) -> bool:
    return stage_index(next_stage) > stage_index(current_stage)


_TERMINAL_STAGES = {"HIRED", "REJECTED", "WITHDRAWN"}
_INTERVIEW_STAGE_TYPES = {
    "ASSESSMENT": "ASSESSMENT",
    "TECHNICAL_INTERVIEW": "TECHNICAL",
    "MANAGERIAL_INTERVIEW": "MANAGERIAL",
    "HR_INTERVIEW": "HR",
}


def create_application(
    session: Session,
    application: Application,
    *,
    actor_id: str,
    actor_name_snapshot: str,
    reason: str,
    actor_type: str = "USER",
) -> Application:
    if not actor_id.strip() or not actor_name_snapshot.strip() or not reason.strip():
        raise ValueError("Application creation requires an actor, name, and reason.")
    if actor_type not in {"USER", "SYSTEM", "SERVICE"}:
        raise ValueError("Unsupported application audit actor type.")
    if application.requisition_id is None and application.requisition is not None:
        application.requisition_id = application.requisition.requisition_id
    if application.candidate_id is None and application.candidate is not None:
        application.candidate_id = application.candidate.candidate_id
    if application.requisition_id is None:
        raise ValueError("An application must reference a requisition.")
    with session.no_autoflush:
        requisition = session.scalar(
            select(Requisition)
            .where(Requisition.requisition_id == application.requisition_id)
            .with_for_update()
        )
    if requisition is None or requisition.status != "OPEN":
        raise ValueError("Applications may only be submitted to an open requisition.")
    if application.current_stage not in {None, "APPLIED"} or application.status not in {None, "ACTIVE"}:
        raise ValueError("New applications must start at APPLIED with ACTIVE status.")
    application.current_stage = "APPLIED"
    application.status = "ACTIVE"
    session.add(application)
    session.flush()
    occurred_at = datetime.now(timezone.utc)
    session.add(
        ApplicationStageHistory(
            stage_history_id=f"STAGE-{uuid4().hex}",
            application_id=application.application_id,
            history_sequence=1,
            previous_stage=None,
            new_stage="APPLIED",
            previous_status=None,
            new_status="ACTIVE",
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=reason,
            occurred_at=occurred_at,
        )
    )
    session.add(
        AuditEvent(
            audit_event_id=f"AUDIT-{uuid4().hex}",
            event_type="CREATE",
            entity_type="APPLICATION",
            entity_id=application.application_id,
            related_entity_type="REQUISITION",
            related_entity_id=requisition.requisition_id,
            new_state="APPLIED/ACTIVE",
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=reason,
        )
    )
    session.flush()
    return application


def transition_application(
    session: Session,
    application_id: str,
    *,
    actor_id: str,
    actor_name_snapshot: str,
    reason: str,
    new_stage: str | None = None,
    new_status: str | None = None,
    required_scorecard_reviewers: AbstractSet[str] = frozenset(),
    actor_type: str = "USER",
) -> Application:
    application = session.scalar(
        select(Application).where(Application.application_id == application_id).with_for_update()
    )
    if application is None:
        raise ValueError(f"Application {application_id!r} does not exist.")
    if not actor_id.strip() or not actor_name_snapshot.strip() or not reason.strip():
        raise ValueError("Application transitions require an actor, name, and reason.")
    if actor_type not in {"USER", "SYSTEM", "SERVICE"}:
        raise ValueError("Unsupported application audit actor type.")
    if application.status == "CLOSED" or application.current_stage in _TERMINAL_STAGES:
        raise ValueError("A terminal application cannot be reopened or changed.")

    previous_stage = application.current_stage
    previous_status = application.status
    target_stage = new_stage or previous_stage
    target_status = new_status or (
        "CLOSED" if target_stage in _TERMINAL_STAGES else previous_status
    )
    if target_stage == previous_stage and target_status == previous_status:
        raise ValueError("An application transition must change stage or status.")
    if target_stage not in {
        "APPLIED", "SCREENING", "ASSESSMENT", "TECHNICAL_INTERVIEW",
        "MANAGERIAL_INTERVIEW", "HR_INTERVIEW", "OFFER", "HIRED", "REJECTED", "WITHDRAWN",
    }:
        raise ValueError(f"Invalid application stage: {target_stage}.")
    if target_status not in {"ACTIVE", "ON_HOLD", "CLOSED"}:
        raise ValueError(f"Invalid application status: {target_status}.")

    if target_stage != previous_stage:
        if previous_status == "ON_HOLD" and target_stage not in {"REJECTED", "WITHDRAWN"}:
            raise ValueError("An on-hold application must be resumed before advancing its stage.")
        if target_status != previous_status and target_stage not in _TERMINAL_STAGES:
            raise ValueError("Stage advancement and hold/resume must be separate transitions.")
        is_terminal_decision = target_stage in {"REJECTED", "WITHDRAWN"}
        next_stage_index = stage_index(target_stage.title().replace("_", " "))
        current_stage_index = stage_index(previous_stage.title().replace("_", " "))
        if is_terminal_decision:
            pass
        elif target_stage == "HIRED":
            accepted_offer = session.scalar(
                select(Offer.offer_id)
                .where(
                    Offer.application_id == application_id,
                    Offer.status == "ACCEPTED",
                )
                .limit(1)
            )
            if accepted_offer is None:
                raise ValueError("An application can be hired only after an offer is accepted.")
        elif next_stage_index != current_stage_index + 1:
            raise ValueError(f"Invalid application transition: {previous_stage} -> {target_stage}.")
        if (
            previous_stage in _INTERVIEW_STAGE_TYPES
            and target_stage != previous_stage
            and target_stage not in {"REJECTED", "WITHDRAWN"}
        ):
            if not required_scorecard_reviewers:
                raise ValueError("Advancing past an interview stage requires configured reviewers.")
            interview_ids = set(
                session.scalars(
                    select(Interview.interview_id).where(
                        Interview.application_id == application_id,
                        Interview.interview_type == _INTERVIEW_STAGE_TYPES[previous_stage],
                        Interview.status == "COMPLETED",
                    )
                )
            )
            if not interview_ids:
                raise ValueError("Advancing past an interview stage requires a completed interview.")
            submitted_pairs = {
                tuple(row)
                for row in session.execute(
                    select(Scorecard.interview_id, Scorecard.reviewer_id).where(
                        Scorecard.interview_id.in_(interview_ids),
                        Scorecard.completion_status == "SUBMITTED",
                    )
                ).all()
            }
            required_pairs = {
                (interview_id, reviewer_id)
                for interview_id in interview_ids
                for reviewer_id in required_scorecard_reviewers
            }
            if not required_pairs.issubset(submitted_pairs):
                raise ValueError("Required reviewers must submit scorecards before stage advancement.")

    if target_stage in _TERMINAL_STAGES:
        if target_status != "CLOSED":
            raise ValueError("Terminal application stages require CLOSED status.")
    elif target_status == "CLOSED":
        raise ValueError("CLOSED status requires a terminal application stage.")
    elif target_status != previous_status and {target_status, previous_status} != {"ACTIVE", "ON_HOLD"}:
        raise ValueError("Application status may only switch between ACTIVE and ON_HOLD.")

    sequence = session.scalar(
        select(func.coalesce(func.max(ApplicationStageHistory.history_sequence), 0)).where(
            ApplicationStageHistory.application_id == application_id
        )
    ) + 1
    occurred_at = datetime.now(timezone.utc)
    application.current_stage = target_stage
    application.status = target_status
    application.updated_at = occurred_at
    session.add(
        ApplicationStageHistory(
            stage_history_id=f"STAGE-{uuid4().hex}",
            application_id=application_id,
            history_sequence=sequence,
            previous_stage=previous_stage,
            new_stage=target_stage,
            previous_status=previous_status,
            new_status=target_status,
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=reason,
            occurred_at=occurred_at,
        )
    )
    session.add(
        AuditEvent(
            audit_event_id=f"AUDIT-{uuid4().hex}",
            event_type="STATE_CHANGE",
            entity_type="APPLICATION",
            entity_id=application_id,
            related_entity_type="REQUISITION",
            related_entity_id=application.requisition_id,
            previous_state=f"{previous_stage}/{previous_status}",
            new_state=f"{target_stage}/{target_status}",
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=reason,
        )
    )
    session.flush()
    return application
