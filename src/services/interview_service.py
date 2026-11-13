from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.business_rules.scheduling_rules import intervals_overlap
from src.models import (
    Application,
    AuditEvent,
    Availability,
    Candidate,
    Interview,
    InterviewPanel,
    InterviewRescheduleHistory,
    Interviewer,
    PanelInterviewer,
)

RESERVING_STATUSES = {"SCHEDULED", "CONFIRMED"}


def is_available(candidate_start: datetime, candidate_end: datetime, booked_slots: list[tuple[datetime, datetime]]) -> bool:
    for start, end in booked_slots:
        if intervals_overlap(start, end, candidate_start, candidate_end):
            return False
    return True


def validate_interview_schedule(
    session: Session,
    interview: Interview,
    *,
    exclude_interview_id: str | None = None,
) -> None:
    start_at = interview.start_at
    end_at = interview.end_at
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise ValueError("Interview start and end must be timezone-aware.")
    duration_seconds = (end_at - start_at).total_seconds()
    if duration_seconds <= 0 or duration_seconds % 60:
        raise ValueError("Interview interval must be positive and a whole number of minutes.")
    if interview.duration_minutes != int(duration_seconds / 60):
        raise ValueError("duration_minutes must equal the interview interval.")

    panel = session.scalar(
        select(InterviewPanel)
        .where(InterviewPanel.panel_id == interview.panel_id)
        .with_for_update()
    )
    if panel is None or panel.active_status != "ACTIVE":
        raise ValueError("Interview scheduling requires an active panel.")
    application = session.scalar(
        select(Application).where(Application.application_id == interview.application_id)
    )
    if application is None:
        raise ValueError("Interview application does not exist.")
    if application.current_stage in {"HIRED", "REJECTED", "WITHDRAWN"}:
        raise ValueError("Terminal applications cannot be scheduled for an interview.")

    first_date: date = start_at.date()
    last_date: date = (end_at - timedelta(microseconds=1)).date()
    memberships = list(
        session.scalars(
            select(PanelInterviewer)
            .where(
                PanelInterviewer.panel_id == interview.panel_id,
                PanelInterviewer.effective_from <= last_date,
                (PanelInterviewer.effective_to.is_(None)) | (PanelInterviewer.effective_to >= first_date),
            )
            .order_by(PanelInterviewer.interviewer_id)
            .with_for_update()
        )
    )
    if not memberships:
        raise ValueError("The panel has no effective interviewer membership for this interval.")
    if any(
        membership.effective_from > first_date
        or (membership.effective_to is not None and membership.effective_to < last_date)
        for membership in memberships
    ):
        raise ValueError("Every panel membership must cover the full interview interval.")
    interviewer_ids = [membership.interviewer_id for membership in memberships]
    if len(set(interviewer_ids)) != len(interviewer_ids):
        raise ValueError("The panel has overlapping duplicate membership for an interviewer.")

    interviewers = list(
        session.scalars(
            select(Interviewer)
            .where(Interviewer.interviewer_id.in_(interviewer_ids))
            .order_by(Interviewer.interviewer_id)
            .with_for_update()
        )
    )
    if len(interviewers) != len(interviewer_ids) or any(
        interviewer.active_status != "ACTIVE" for interviewer in interviewers
    ):
        raise ValueError("Every panel member must be an active interviewer.")

    availability_rows = list(
        session.scalars(
            select(Availability)
            .where(
                Availability.interviewer_id.in_(interviewer_ids),
                Availability.availability_status == "AVAILABLE",
                Availability.available_start <= start_at,
                Availability.available_end >= end_at,
            )
            .with_for_update()
        )
    )
    covered_interviewers = {row.interviewer_id for row in availability_rows}
    if covered_interviewers != set(interviewer_ids):
        raise ValueError("Every interviewer assigned to the panel must be available for the full interval.")

    candidate = session.scalar(
        select(Candidate)
        .where(Candidate.candidate_id == application.candidate_id)
        .with_for_update()
    )
    if candidate is None:
        raise ValueError("Interview candidate does not exist.")

    overlapping_interviews = list(
        session.scalars(
            select(Interview)
            .where(
                Interview.status.in_(RESERVING_STATUSES),
                Interview.start_at < end_at,
                Interview.end_at > start_at,
                Interview.interview_id != (exclude_interview_id or ""),
            )
        )
    )
    for existing in overlapping_interviews:
        existing_application = session.get(Application, existing.application_id)
        if existing_application is not None and existing_application.candidate_id == candidate.candidate_id:
            raise ValueError("The candidate has an overlapping scheduled interview.")
        overlap_start = max(start_at, existing.start_at).date()
        overlap_end = (min(end_at, existing.end_at) - timedelta(microseconds=1)).date()
        conflict_members = session.scalars(
            select(PanelInterviewer).where(
                PanelInterviewer.panel_id == existing.panel_id,
                PanelInterviewer.interviewer_id.in_(interviewer_ids),
                PanelInterviewer.effective_from <= overlap_end,
                (PanelInterviewer.effective_to.is_(None)) | (PanelInterviewer.effective_to >= overlap_start),
            )
        )
        if any(True for _ in conflict_members):
            raise ValueError("A panel interviewer has an overlapping scheduled interview.")


def schedule_interview(session: Session, interview: Interview) -> Interview:
    if interview.status is None:
        interview.status = "SCHEDULED"
    if interview.status not in RESERVING_STATUSES:
        raise ValueError("A new interview must reserve a calendar slot.")
    validate_interview_schedule(session, interview)
    session.add(interview)
    session.add(
        AuditEvent(
            audit_event_id=f"AUDIT-{uuid4().hex}",
            event_type="CREATE",
            entity_type="INTERVIEW",
            entity_id=interview.interview_id,
            new_state=interview.status,
            actor_type="SERVICE",
            actor_id=interview.scheduled_by,
        )
    )
    session.flush()
    return interview


def reschedule_interview(
    session: Session,
    interview_id: str,
    *,
    new_start_at: datetime,
    new_end_at: datetime,
    actor_id: str,
    actor_name_snapshot: str,
    reason: str,
) -> Interview:
    interview = session.scalar(
        select(Interview).where(Interview.interview_id == interview_id).with_for_update()
    )
    if interview is None:
        raise ValueError(f"Interview {interview_id!r} does not exist.")
    if interview.status not in RESERVING_STATUSES:
        raise ValueError("Only scheduled or confirmed interviews can be rescheduled.")
    if not reason.strip():
        raise ValueError("A reschedule reason is required.")
    if not actor_id.strip() or not actor_name_snapshot.strip():
        raise ValueError("A reschedule requires actor identity and name.")

    previous_start_at = interview.start_at
    previous_end_at = interview.end_at
    duration_seconds = (new_end_at - new_start_at).total_seconds()
    if duration_seconds <= 0 or duration_seconds % 60:
        raise ValueError("Rescheduled interval must be positive and a whole number of minutes.")
    proposed = Interview(
        interview_id=interview.interview_id,
        application_id=interview.application_id,
        panel_id=interview.panel_id,
        interview_round=interview.interview_round,
        interview_type=interview.interview_type,
        start_at=new_start_at,
        end_at=new_end_at,
        duration_minutes=int(duration_seconds / 60),
        status=interview.status,
    )
    validate_interview_schedule(session, proposed, exclude_interview_id=interview_id)
    interview.start_at = new_start_at
    interview.end_at = new_end_at
    interview.duration_minutes = int(duration_seconds / 60)

    sequence = session.scalar(
        select(func.coalesce(func.max(InterviewRescheduleHistory.reschedule_sequence), 0)).where(
            InterviewRescheduleHistory.interview_id == interview_id
        )
    ) + 1
    session.add(
        InterviewRescheduleHistory(
            reschedule_history_id=f"RESCHED-{uuid4().hex}",
            interview_id=interview_id,
            reschedule_sequence=sequence,
            previous_start_at=previous_start_at,
            previous_end_at=previous_end_at,
            new_start_at=new_start_at,
            new_end_at=new_end_at,
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=reason,
        )
    )
    session.add(
        AuditEvent(
            audit_event_id=f"AUDIT-RESCHED-{interview_id}-{sequence:06d}",
            event_type="STATE_CHANGE",
            entity_type="INTERVIEW",
            entity_id=interview_id,
            related_entity_type="APPLICATION",
            related_entity_id=interview.application_id,
            previous_state=f"{previous_start_at.isoformat()}/{previous_end_at.isoformat()}",
            new_state=f"{new_start_at.isoformat()}/{new_end_at.isoformat()}",
            actor_type="USER",
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=reason,
        )
    )
    session.flush()
    return interview
