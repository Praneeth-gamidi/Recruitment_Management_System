from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models import (
    AuditEvent,
    HiringManager,
    Interviewer,
    Permission,
    Requisition,
    Role,
    RolePermission,
    User,
    UserRole,
)
from src.rbac.seed import ROLE_BY_CODE

ACTIVE_ACCOUNT_STATUS = "ACTIVE"
ACCOUNT_UNAVAILABLE_MESSAGE = "Account is not available."
PROVISIONING_FAILURE_MESSAGE = "Account could not be provisioned."


class AccountUnavailableError(LookupError):
    """Raised when an account is missing or is not active."""


class AccountAuthorizationError(PermissionError):
    """Raised when an actor is not authorized to perform an account operation."""


class AccountProvisioningError(ValueError):
    """Raised when account input or related profile data is invalid."""


class AccountConflictError(AccountProvisioningError):
    """Raised without revealing which account or profile value conflicted."""


@dataclass(frozen=True)
class RoleGrantRequest:
    role_code: str
    scope_type: str
    scope_department: str | None = None
    scope_requisition_id: str | None = None


def normalize_email(email: str) -> str:
    """Normalize an email for storage using trimmed lowercase form."""
    if not isinstance(email, str):
        raise AccountProvisioningError("A valid email address is required.")
    normalized = email.strip().lower()
    if (
        not normalized
        or len(normalized) > 320
        or normalized.count("@") != 1
        or any(character.isspace() or ord(character) < 33 or ord(character) == 127
               for character in normalized)
    ):
        raise AccountProvisioningError("A valid email address is required.")
    local_part, domain = normalized.split("@")
    if not local_part or not domain or local_part.startswith(".") or local_part.endswith("."):
        raise AccountProvisioningError("A valid email address is required.")
    if ".." in local_part or domain.startswith(".") or domain.endswith(".") or ".." in domain:
        raise AccountProvisioningError("A valid email address is required.")
    return normalized


def _normalize_display_name(display_name: str) -> str:
    if not isinstance(display_name, str):
        raise AccountProvisioningError("A valid display name is required.")
    normalized = display_name.strip()
    if not normalized or len(normalized) > 200 or "\x00" in normalized:
        raise AccountProvisioningError("A valid display name is required.")
    return normalized


def require_active_account(session: Session, user_id: str | None) -> User:
    """Return an ACTIVE account; missing and inactive accounts share one error."""
    if not user_id:
        raise AccountUnavailableError(ACCOUNT_UNAVAILABLE_MESSAGE)
    user = session.scalar(
        select(User).where(
            User.user_id == user_id,
            User.status == ACTIVE_ACCOUNT_STATUS,
        ).execution_options(populate_existing=True)
    )
    if user is None:
        raise AccountUnavailableError(ACCOUNT_UNAVAILABLE_MESSAGE)
    return user


def _actor_has_global_permission(
    session: Session,
    actor_user_id: str,
    permission_code: str,
) -> bool:
    return session.scalar(
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            UserRole.user_id == actor_user_id,
            UserRole.revoked_at.is_(None),
            UserRole.scope_type == "GLOBAL",
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
            Permission.permission_code == permission_code,
        )
        .limit(1)
    ) is not None


def _validate_role_grant(
    session: Session,
    grant: RoleGrantRequest,
    *,
    hiring_manager_id: str | None,
    interviewer_id: str | None,
) -> Role:
    if not isinstance(grant, RoleGrantRequest) or grant.role_code not in ROLE_BY_CODE:
        raise AccountProvisioningError("Only approved built-in roles may be assigned.")
    role = session.scalar(
        select(Role).where(
            Role.role_code == grant.role_code,
            Role.is_system.is_(True),
            Role.is_active.is_(True),
        )
    )
    if role is None:
        raise AccountProvisioningError("Only active approved built-in roles may be assigned.")

    if grant.role_code == "ADMIN":
        valid_scope = (
            grant.scope_type == "GLOBAL"
            and grant.scope_department is None
            and grant.scope_requisition_id is None
        )
    elif grant.role_code == "RECRUITER":
        valid_scope = (
            grant.scope_type == "DEPARTMENT"
            and bool(grant.scope_department and grant.scope_department.strip())
            and len(grant.scope_department.strip()) <= 100
            and grant.scope_requisition_id is None
        ) or (
            grant.scope_type == "REQUISITION"
            and grant.scope_department is None
            and bool(grant.scope_requisition_id and grant.scope_requisition_id.strip())
        )
        if valid_scope and grant.scope_type == "REQUISITION":
            valid_scope = session.get(Requisition, grant.scope_requisition_id) is not None
    elif grant.role_code == "HIRING_MANAGER":
        valid_scope = (
            grant.scope_type == "RESOURCE"
            and grant.scope_department is None
            and grant.scope_requisition_id is None
            and hiring_manager_id is not None
        )
    elif grant.role_code == "INTERVIEWER":
        valid_scope = (
            grant.scope_type == "RESOURCE"
            and grant.scope_department is None
            and grant.scope_requisition_id is None
            and interviewer_id is not None
        )
    else:
        valid_scope = (
            grant.scope_type == "RESOURCE"
            and grant.scope_department is None
            and grant.scope_requisition_id is None
        )

    if not valid_scope:
        raise AccountProvisioningError("Role grant scope is invalid.")
    return role


def provision_user(
    session: Session,
    *,
    actor_user_id: str,
    email: str,
    display_name: str,
    hiring_manager_id: str | None = None,
    interviewer_id: str | None = None,
    role_grants: Sequence[RoleGrantRequest] = (),
) -> User:
    """Provision a pending staff account in the caller's transaction.

    The caller owns the outer transaction and must commit it. The account,
    explicitly requested role grants, and audit event are flushed in one
    savepoint so a failed insert cannot leave a partial provisioned account.
    """
    normalized_email = normalize_email(email)
    normalized_name = _normalize_display_name(display_name)

    actor = require_active_account(session, actor_user_id)
    if not _actor_has_global_permission(session, actor.user_id, "users.manage"):
        raise AccountAuthorizationError("Account operation is not permitted.")
    if role_grants and not _actor_has_global_permission(
        session, actor.user_id, "roles.manage"
    ):
        raise AccountAuthorizationError("Account operation is not permitted.")

    if session.scalar(select(User.user_id).where(User.email == normalized_email)) is not None:
        raise AccountConflictError(PROVISIONING_FAILURE_MESSAGE)

    if hiring_manager_id is not None:
        profile = session.get(HiringManager, hiring_manager_id)
        linked = session.scalar(
            select(User.user_id).where(User.hiring_manager_id == hiring_manager_id)
        )
        if profile is None or linked is not None:
            raise AccountConflictError(PROVISIONING_FAILURE_MESSAGE)
    if interviewer_id is not None:
        profile = session.get(Interviewer, interviewer_id)
        linked = session.scalar(
            select(User.user_id).where(User.interviewer_id == interviewer_id)
        )
        if profile is None or linked is not None:
            raise AccountConflictError(PROVISIONING_FAILURE_MESSAGE)

    user = User(
        user_id=f"USR-{uuid4()}",
        email=normalized_email,
        display_name=normalized_name,
        status="PENDING_ACTIVATION",
        password_hash=None,
        hiring_manager_id=hiring_manager_id,
        interviewer_id=interviewer_id,
    )
    if user.user_id == actor.user_id:
        raise AccountAuthorizationError("Account operation is not permitted.")

    role_rows: list[UserRole] = []
    seen_grants: set[tuple[str, str, str | None, str | None]] = set()
    for grant in role_grants:
        role = _validate_role_grant(
            session,
            grant,
            hiring_manager_id=hiring_manager_id,
            interviewer_id=interviewer_id,
        )
        grant_key = (
            grant.role_code,
            grant.scope_type,
            grant.scope_department.strip() if grant.scope_department else None,
            grant.scope_requisition_id,
        )
        if grant_key in seen_grants:
            raise AccountProvisioningError("Duplicate role grants are not allowed.")
        seen_grants.add(grant_key)
        role_rows.append(
            UserRole(
                user_id=user.user_id,
                role_id=role.role_id,
                scope_type=grant.scope_type,
                scope_department=(
                    grant.scope_department.strip() if grant.scope_department else None
                ),
                scope_requisition_id=grant.scope_requisition_id,
                assigned_by_user_id=actor.user_id,
            )
        )

    audit_event = AuditEvent(
        audit_event_id=f"AUDIT-{uuid4().hex}",
        event_type="USER_PROVISIONED",
        entity_type="USER",
        entity_id=user.user_id,
        previous_state=None,
        new_state="PENDING_ACTIVATION",
        actor_type="USER",
        actor_id=actor.user_id,
        actor_name_snapshot=actor.display_name,
    )
    try:
        with session.begin_nested():
            session.add(user)
            session.add_all(role_rows)
            session.add(audit_event)
            session.flush()
    except IntegrityError:
        raise AccountConflictError(PROVISIONING_FAILURE_MESSAGE) from None
    return user
