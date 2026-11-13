from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Approval, AuditEvent, RequisitionApproval

ALLOWED_APPROVAL_STATES = {"Pending", "Approved", "Rejected", "Returned for revision"}
DECISIONS = {"APPROVED", "REJECTED", "RETURNED_FOR_REVISION"}


def is_valid_approval_state(state: str) -> bool:
    return state in ALLOWED_APPROVAL_STATES


def _validate_decision(decision: str, comments: str | None) -> None:
    if decision not in DECISIONS:
        raise ValueError(f"Unsupported approval decision: {decision}.")
    if decision in {"REJECTED", "RETURNED_FOR_REVISION"} and not (comments and comments.strip()):
        raise ValueError("Rejected or returned approvals require comments.")


def decide_requisition_approval(
    session: Session,
    requisition_approval_id: str,
    decision: str,
    *,
    actor_id: str,
    actor_name_snapshot: str,
    comments: str | None = None,
) -> RequisitionApproval:
    _validate_decision(decision, comments)
    approval = session.scalar(
        select(RequisitionApproval)
        .where(RequisitionApproval.requisition_approval_id == requisition_approval_id)
        .with_for_update()
    )
    if approval is None:
        raise ValueError(f"Requisition approval {requisition_approval_id!r} does not exist.")
    if approval.decision != "PENDING":
        raise ValueError("A requisition approval decision is immutable once decided.")
    if approval.approver_id != actor_id:
        raise ValueError("Only the assigned requisition approver may record this decision.")
    if not actor_name_snapshot.strip():
        raise ValueError("Approval decisions require the actor name snapshot.")

    approval.decision = decision
    approval.comments = comments
    approval.decided_at = datetime.now(timezone.utc)
    session.add(
        AuditEvent(
            audit_event_id=f"AUDIT-{uuid4().hex}",
            event_type="APPROVAL_DECISION",
            entity_type="REQUISITION_APPROVAL",
            entity_id=requisition_approval_id,
            related_entity_type="REQUISITION",
            related_entity_id=approval.requisition_id,
            previous_state="PENDING",
            new_state=decision,
            actor_type="USER",
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=comments,
        )
    )
    session.flush()
    return approval


def decide_offer_approval(
    session: Session,
    approval_id: str,
    decision: str,
    *,
    actor_id: str,
    actor_name_snapshot: str,
    comments: str | None = None,
) -> Approval:
    _validate_decision(decision, comments)
    approval = session.scalar(
        select(Approval).where(Approval.approval_id == approval_id).with_for_update()
    )
    if approval is None:
        raise ValueError(f"Offer approval {approval_id!r} does not exist.")
    if approval.decision != "PENDING":
        raise ValueError("An offer approval decision is immutable once decided.")
    if approval.approver_id != actor_id:
        raise ValueError("Only the assigned offer approver may record this decision.")
    if not actor_name_snapshot.strip():
        raise ValueError("Approval decisions require the actor name snapshot.")

    approval.decision = decision
    approval.comments = comments
    approval.decided_at = datetime.now(timezone.utc)
    session.add(
        AuditEvent(
            audit_event_id=f"AUDIT-{uuid4().hex}",
            event_type="APPROVAL_DECISION",
            entity_type="APPROVAL",
            entity_id=approval_id,
            related_entity_type="OFFER",
            related_entity_id=approval.offer_id,
            previous_state="PENDING",
            new_state=decision,
            actor_type="USER",
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=comments,
        )
    )
    session.flush()
    return approval
