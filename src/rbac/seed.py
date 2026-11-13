from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.auth import Permission, Role, RolePermission

RBAC_NAMESPACE = UUID("60dbe960-3482-46bb-9898-020ad2dd9519")


@dataclass(frozen=True)
class RoleDefinition:
    code: str
    name: str
    description: str
    permissions: tuple[str, ...]


@dataclass(frozen=True)
class PermissionDefinition:
    code: str
    description: str
    roles: tuple[str, ...]
    resource_scope: str
    workflow_check: str


ROLE_DEFINITIONS = (
    RoleDefinition(
        "ADMIN",
        "Admin",
        "Provision/deactivate users, manage role and permission configuration, view system-wide recruitment data and audit events.",
        (
            "users.manage",
            "roles.manage",
            "permissions.read",
            "configuration.manage",
            "requisitions.read",
            "candidates.read",
            "applications.read",
            "interviews.read",
            "scorecards.read",
            "offers.read",
            "audit.read",
        ),
    ),
    RoleDefinition(
        "RECRUITER",
        "Recruiter",
        "Create/manage requisitions, candidates, and applications; make permitted stage changes; schedule/reschedule interviews; initiate offers.",
        (
            "requisitions.read",
            "requisitions.create",
            "requisitions.update",
            "candidates.read",
            "candidates.create",
            "candidates.update",
            "applications.read",
            "applications.manage",
            "applications.transition",
            "interviews.read",
            "interviews.schedule",
            "interviews.reschedule",
            "scorecards.read",
            "offers.read",
            "offers.create",
        ),
    ),
    RoleDefinition(
        "HIRING_MANAGER",
        "Hiring Manager",
        "Review assigned requisitions and candidates, record hiring recommendations, and view submitted interview feedback.",
        (
            "requisitions.read",
            "candidates.read",
            "applications.read",
            "hiring.recommend",
            "interviews.read",
            "scorecards.read",
            "offers.read",
        ),
    ),
    RoleDefinition(
        "INTERVIEWER",
        "Interviewer",
        "View assigned interviews and minimum candidate context; submit and view own scorecards.",
        (
            "candidates.read",
            "applications.read",
            "interviews.read",
            "scorecards.submit",
            "scorecards.read",
        ),
    ),
    RoleDefinition(
        "APPROVER",
        "Approver",
        "Decide assigned requisition/offer approvals and compensation exceptions.",
        (
            "requisitions.read",
            "requisitions.approve",
            "candidates.read",
            "applications.read",
            "scorecards.read",
            "offers.read",
            "offers.approve",
            "compensation_exceptions.approve",
            "audit.read",
        ),
    ),
)

PERMISSION_DEFINITIONS = (
    PermissionDefinition("users.manage", "Provision, list, read, and update user accounts and status.", ("ADMIN",), "Global; self-escalation and last-Admin safeguards apply.", "Activation, verified email, status lifecycle, and session revocation rules apply."),
    PermissionDefinition("roles.manage", "Create/manage role definitions and assign/revoke role grants.", ("ADMIN",), "Global administration; grants limited to delegable permissions.", "Cannot self-assign, mutate protected built-in roles, or remove the last active Admin."),
    PermissionDefinition("permissions.read", "Read the canonical permission catalog.", ("ADMIN",), "Global catalog only.", "Read-only; no permission mutation."),
    PermissionDefinition("configuration.manage", "Manage system configuration.", ("ADMIN",), "Global configuration.", "Sensitive configuration changes are audited; secrets are never returned."),
    PermissionDefinition("requisitions.read", "Read requisition fields needed by the user's assigned work.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "APPROVER"), "Admin global; Recruiter granted department/requisition; Hiring Manager linked owner; Approver assigned approval only.", "Approval access exposes only decision context."),
    PermissionDefinition("requisitions.create", "Create a requisition.", ("RECRUITER",), "Explicit recruiter department or requisition scope.", "New requisition starts in DRAFT; opening requires all required requisition approvals."),
    PermissionDefinition("requisitions.update", "Edit permitted requisition fields.", ("RECRUITER",), "Explicit recruiter department/requisition scope.", "Lifecycle transitions and protected/approved compensation changes follow business rules."),
    PermissionDefinition("requisitions.approve", "Decide an assigned requisition approval.", ("APPROVER",), "Exact assigned RequisitionApproval and related requisition.", "Must match approver_id; decision immutable; requester/owner self-approval prohibited when separation policy applies."),
    PermissionDefinition("hiring.recommend", "Record a Hiring Manager's candidate/hiring recommendation.", ("HIRING_MANAGER",), "Applications under requisitions owned by the linked HiringManager profile.", "Recommendation is not an approval and cannot bypass stage or approval workflow gates."),
    PermissionDefinition("candidates.read", "Read candidate details required for assigned recruitment work.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER", "APPROVER"), "Admin global audited; Recruiter scoped; Hiring Manager owned requisitions; Interviewer assigned interview; Approver assigned decision context.", "Candidate fields are minimized/redacted; no global candidate search for non-admin roles."),
    PermissionDefinition("candidates.create", "Create a candidate profile.", ("RECRUITER",), "Explicit recruiter department/requisition scope and authorized intake.", "Validate duplicate identity and privacy/consent policy."),
    PermissionDefinition("candidates.update", "Update candidate profile fields.", ("RECRUITER",), "Only candidates accessible through the recruiter's scoped applications/requisitions.", "Sensitive/contact field edits are audited; no access via guessed IDs."),
    PermissionDefinition("applications.read", "Read applications and status needed for authorized work.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER", "APPROVER"), "Admin global audited; Recruiter scoped; Hiring Manager owned requisitions; Interviewer assigned interview only; Approver assigned approval context.", "Return only fields necessary to role's task."),
    PermissionDefinition("applications.manage", "Manage application records other than stage transitions.", ("RECRUITER",), "Explicit recruiter department/requisition scope.", "Candidate/requisition pair uniqueness and application lifecycle constraints apply."),
    PermissionDefinition("applications.transition", "Move an application through permitted stages.", ("RECRUITER",), "Explicit recruiter department/requisition scope.", "Only documented stage transitions; required reviews/approvals and terminal-state rules apply."),
    PermissionDefinition("interviews.read", "Read interview details and schedules.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER"), "Admin global audited; Recruiter scoped; Hiring Manager owned requisitions; Interviewer effective panel membership.", "Interviewer sees only assigned interviews and minimum candidate context."),
    PermissionDefinition("interviews.schedule", "Schedule an interview.", ("RECRUITER",), "Explicit recruiter department/requisition scope.", "Service validates panel membership, each interviewer's availability, candidate availability, and conflicts transactionally."),
    PermissionDefinition("interviews.reschedule", "Reschedule an interview.", ("RECRUITER",), "Explicit recruiter department/requisition scope.", "Availability/conflict checks repeat; immutable reschedule history is appended with reason."),
    PermissionDefinition("scorecards.submit", "Create/submit a review scorecard.", ("INTERVIEWER",), "Own linked interviewer profile, assigned interview, and active panel membership.", "Reviewer identity must match; criteria/rating requirements apply; revisions are explicit and immutable after submission."),
    PermissionDefinition("scorecards.read", "Read scorecards and review feedback.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER", "APPROVER"), "Admin global audited; Recruiter metadata only in scope; Hiring Manager submitted feedback for owned requisitions; Interviewer own scorecards; Approver only when decision policy requires.", "Draft content is not visible to unauthorized reviewers; least-privilege fields apply."),
    PermissionDefinition("offers.read", "Read offer terms and status required for authorized work.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "APPROVER"), "Admin global audited; Recruiter scoped; Hiring Manager owned requisition; Approver assigned approval.", "Compensation fields are restricted to users with a business need."),
    PermissionDefinition("offers.create", "Initiate a new offer version.", ("RECRUITER",), "Explicit recruiter department/requisition scope.", "Offer snapshots compensation band; required standard and exception approvals gate approval/send/acceptance."),
    PermissionDefinition("offers.approve", "Decide an assigned standard offer approval.", ("APPROVER",), "Exact assigned Approval and related offer.", "Must match approver_id; recruiter/creator cannot approve own offer; immutable ordered decision workflow applies."),
    PermissionDefinition("compensation_exceptions.approve", "Decide an assigned compensation exception approval.", ("APPROVER",), "Exact assigned Approval with type COMPENSATION_EXCEPTION.", "Must match assigned approver; documented exception reason and separation-of-duties checks apply."),
    PermissionDefinition("audit.read", "Read audit events.", ("ADMIN", "APPROVER"), "Admin global; Approver only assigned approval-related event records if policy allows.", "Read-only, audited access; unrelated candidate data is not exposed."),
)

ROLE_BY_CODE = {definition.code: definition for definition in ROLE_DEFINITIONS}
PERMISSION_BY_CODE = {definition.code: definition for definition in PERMISSION_DEFINITIONS}


def stable_id(entity: str, code: str) -> UUID:
    return uuid5(RBAC_NAMESPACE, f"{entity}:{code}")


def seed_rbac(session: Session) -> None:
    """Insert canonical RBAC definitions without overwriting existing records."""
    roles: dict[str, Role] = {}
    for definition in ROLE_DEFINITIONS:
        role = session.scalar(select(Role).where(Role.role_code == definition.code))
        if role is None:
            role = Role(
                role_id=stable_id("role", definition.code),
                role_code=definition.code,
                name=definition.name,
                description=definition.description,
                is_system=True,
                is_active=True,
            )
            session.add(role)
        elif (
            role.name != definition.name
            or role.description != definition.description
            or not role.is_system
            or not role.is_active
        ):
            raise ValueError(f"Existing built-in role {definition.code!r} differs from its canonical definition.")
        roles[definition.code] = role
    session.flush()

    permissions: dict[str, Permission] = {}
    for definition in PERMISSION_DEFINITIONS:
        permission = session.scalar(
            select(Permission).where(Permission.permission_code == definition.code)
        )
        if permission is None:
            permission = Permission(
                permission_id=stable_id("permission", definition.code),
                permission_code=definition.code,
                description=definition.description,
                is_active=True,
            )
            session.add(permission)
        elif permission.description != definition.description or not permission.is_active:
            raise ValueError(
                f"Existing permission {definition.code!r} differs from its canonical definition."
            )
        permissions[definition.code] = permission
    session.flush()

    expected: set[tuple[UUID, UUID]] = set()
    for permission_definition in PERMISSION_DEFINITIONS:
        for role_code in permission_definition.roles:
            expected.add(
                (
                    roles[role_code].role_id,
                    permissions[permission_definition.code].permission_id,
                )
            )
    existing_rows = session.scalars(select(RolePermission)).all()
    existing = {(row.role_id, row.permission_id) for row in existing_rows}
    if not existing.issubset(expected):
        raise ValueError("Existing built-in role-permission grants contain non-canonical assignments.")
    for role_id, permission_id in expected - existing:
        session.add(RolePermission(role_id=role_id, permission_id=permission_id))
    session.flush()
