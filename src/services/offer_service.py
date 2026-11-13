from __future__ import annotations

from collections.abc import Set as AbstractSet
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.business_rules.compensation_rules import offer_within_band
from src.models import Approval, AuditEvent, Offer


def validate_offer(offer_salary: float, min_salary: float, max_salary: float) -> bool:
    return offer_within_band(offer_salary, min_salary, max_salary)


_OFFER_TRANSITIONS = {
    "DRAFT": {"PENDING_APPROVAL"},
    "PENDING_APPROVAL": {"APPROVED", "RETURNED_FOR_REVISION", "REJECTED", "WITHDRAWN"},
    "RETURNED_FOR_REVISION": {"WITHDRAWN"},
    "APPROVED": {"SENT", "WITHDRAWN"},
    "SENT": {"ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN"},
    "ACCEPTED": set(),
    "DECLINED": set(),
    "EXPIRED": set(),
    "REJECTED": set(),
    "WITHDRAWN": set(),
}


def _validate_approval_gates(
    session: Session,
    offer: Offer,
    required_approval_stages: set[str],
) -> None:
    if not required_approval_stages:
        raise ValueError("Offer progression requires configured approval stages.")
    approvals = list(
        session.scalars(select(Approval).where(Approval.offer_id == offer.offer_id).with_for_update())
    )
    standard = [approval for approval in approvals if approval.approval_type == "STANDARD"]
    stages = {approval.approval_stage: approval for approval in standard}
    if len(stages) != len(standard):
        raise ValueError("Offer approval sequence contains duplicate standard stages.")
    if any(stage not in stages or stages[stage].decision != "APPROVED" for stage in required_approval_stages):
        raise ValueError("All configured standard offer approvals must be approved.")
    if any(approval.decision != "APPROVED" for approval in standard):
        raise ValueError("Every recorded standard offer approval must be approved.")

    outside_band = not (
        offer.band_min_snapshot <= offer.proposed_salary <= offer.band_max_snapshot
    )
    if outside_band:
        exceptions = [
            approval
            for approval in approvals
            if approval.approval_type == "COMPENSATION_EXCEPTION"
        ]
        if not exceptions or any(approval.decision != "APPROVED" for approval in exceptions):
            raise ValueError("Out-of-band offers require approved compensation-exception approvals.")


def transition_offer(
    session: Session,
    offer_id: str,
    next_status: str,
    *,
    required_approval_stages: AbstractSet[str] = frozenset(),
    actor_id: str,
    actor_name_snapshot: str,
    reason: str,
) -> Offer:
    offer = session.scalar(select(Offer).where(Offer.offer_id == offer_id).with_for_update())
    if offer is None:
        raise ValueError(f"Offer {offer_id!r} does not exist.")
    if next_status not in _OFFER_TRANSITIONS.get(offer.status, set()):
        raise ValueError(f"Invalid offer transition: {offer.status} -> {next_status}.")
    if not reason.strip() or not actor_id.strip() or not actor_name_snapshot.strip():
        raise ValueError("Offer transitions require an actor, name, and reason.")

    now = datetime.now(timezone.utc)
    if next_status in {"APPROVED", "SENT", "ACCEPTED"}:
        _validate_approval_gates(session, offer, set(required_approval_stages))
    if next_status == "SENT":
        if offer.offer_date is None or offer.joining_date is None:
            raise ValueError("An offer date and joining date are required before sending an offer.")
        if offer.expires_at is not None and offer.expires_at <= now:
            raise ValueError("An expired offer cannot be sent.")
        offer.sent_at = now
    elif next_status == "ACCEPTED":
        if offer.sent_at is None or (offer.expires_at is not None and offer.expires_at <= now):
            raise ValueError("Only a sent, unexpired offer can be accepted.")
        offer.accepted_at = now
    elif next_status == "DECLINED":
        if offer.sent_at is None:
            raise ValueError("Only a sent offer can be declined.")
        offer.declined_at = now
    elif next_status == "EXPIRED":
        if offer.sent_at is None or offer.expires_at is None or offer.expires_at > now:
            raise ValueError("Only a sent offer whose expiry time has passed can expire.")

    previous_status = offer.status
    offer.status = next_status
    offer.updated_at = now
    session.add(
        AuditEvent(
            audit_event_id=f"AUDIT-{uuid4().hex}",
            event_type="STATE_CHANGE",
            entity_type="OFFER",
            entity_id=offer.offer_id,
            related_entity_type="APPLICATION",
            related_entity_id=offer.application_id,
            previous_state=previous_status,
            new_state=next_status,
            actor_type="USER",
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=reason,
        )
    )
    session.flush()
    return offer
