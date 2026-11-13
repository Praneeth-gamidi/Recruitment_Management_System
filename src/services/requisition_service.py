from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.business_rules.stage_transitions import is_valid_transition
from src.models import AuditEvent, HiringManager, Requisition, RequisitionApproval


def can_transition(current_stage: str, next_stage: str) -> bool:
    return is_valid_transition(current_stage, next_stage)


_REQUISITION_TRANSITIONS = {
    "DRAFT": {"PENDING_APPROVAL", "CANCELLED"},
    "PENDING_APPROVAL": {"DRAFT", "OPEN", "CANCELLED"},
    "OPEN": {"ON_HOLD", "FILLED", "CLOSED", "CANCELLED"},
    "ON_HOLD": {"OPEN", "CLOSED", "CANCELLED"},
    "FILLED": {"CLOSED"},
    "CLOSED": set(),
    "CANCELLED": set(),
}


def transition_requisition(
    session: Session,
    requisition_id: str,
    next_status: str,
    *,
    required_approval_stages: Iterable[str] = (),
    actor_id: str | None = None,
    actor_name_snapshot: str | None = None,
    reason: str,
    actor_type: str = "USER",
) -> Requisition:
    requisition = session.scalar(
        select(Requisition)
        .where(Requisition.requisition_id == requisition_id)
        .with_for_update()
    )
    if requisition is None:
        raise ValueError(f"Requisition {requisition_id!r} does not exist.")
    if next_status not in _REQUISITION_TRANSITIONS.get(requisition.status, set()):
        raise ValueError(f"Invalid requisition transition: {requisition.status} -> {next_status}.")
    if not reason.strip():
        raise ValueError("A requisition transition reason is required.")
    if actor_type == "USER" and (not actor_id or not actor_name_snapshot):
        raise ValueError("User requisition transitions require actor identity and name.")

    previous_status = requisition.status
    if next_status == "OPEN":
        required_stages = set(required_approval_stages)
        if not required_stages:
            raise ValueError("Opening a requisition requires configured approval stages.")
        if (
            requisition.min_salary is None
            or requisition.max_salary is None
            or requisition.min_salary <= 0
            or requisition.min_salary > requisition.max_salary
            or not requisition.currency_code
            or not requisition.compensation_period
        ):
            raise ValueError("Opening requires a complete, positive compensation band.")
        manager = session.get(HiringManager, requisition.hiring_manager_id)
        if manager is None or manager.active_status != "ACTIVE":
            raise ValueError("Opening requires an active hiring manager.")

        current_cycle = session.scalar(
            select(func.max(RequisitionApproval.approval_cycle)).where(
                RequisitionApproval.requisition_id == requisition_id
            )
        )
        if current_cycle is None:
            raise ValueError("Opening requires approved requisition approvals.")
        approvals = list(
            session.scalars(
                select(RequisitionApproval)
                .where(
                    RequisitionApproval.requisition_id == requisition_id,
                    RequisitionApproval.approval_cycle == current_cycle,
                )
                .with_for_update()
            )
        )
        by_stage = {approval.approval_stage: approval for approval in approvals}
        if len(by_stage) != len(approvals):
            raise ValueError("The current requisition approval cycle contains duplicate approval stages.")
        missing_or_unapproved = [
            stage
            for stage in required_stages
            if stage not in by_stage or by_stage[stage].decision != "APPROVED"
        ]
        if missing_or_unapproved or any(approval.decision != "APPROVED" for approval in approvals):
            raise ValueError(
                "The current requisition approval cycle is incomplete or not fully approved: "
                + ", ".join(sorted(missing_or_unapproved or {
                    approval.approval_stage for approval in approvals if approval.decision != "APPROVED"
                }))
            )
        requisition.approved_at = datetime.now(timezone.utc)

    requisition.status = next_status
    session.add(
        AuditEvent(
            audit_event_id=f"AUDIT-{uuid4().hex}",
            event_type="STATE_CHANGE",
            entity_type="REQUISITION",
            entity_id=requisition_id,
            previous_state=previous_status,
            new_state=next_status,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=reason,
        )
    )
    session.flush()
    return requisition
