from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from ipaddress import ip_address
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.api.dependencies.auth import (
    get_authenticated_user,
    has_permission,
    require_permission,
)
from src.database.session import get_db
from src.models import (
    Application,
    ApplicationStageHistory,
    AuditEvent,
    Candidate,
    CandidateSkill,
    HiringManager,
    Offer,
    Permission,
    Requisition,
    RequisitionApproval,
    Role,
    RolePermission,
    Skill,
    UserRole,
    User,
)
from src.schemas.recruitment_schema import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationTransition,
    CandidateCreate,
    CandidateRead,
    HiringManagerCreate,
    HiringManagerRead,
    PublicApplicationCreate,
    RequisitionApprovalDecision,
    RequisitionApprovalSubmission,
    RequisitionCreate,
    RequisitionLifecycleReason,
    RequisitionRead,
    RequisitionUpdate,
)
from src.business_rules.stage_transitions import STAGE_SEQUENCE
from src.services.application_service import create_application, transition_application
from src.services.approval_service import decide_requisition_approval
from src.services.requisition_service import transition_requisition


def require_local_api_caller(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    try:
        is_local = ip_address(client_host).is_loopback
    except ValueError:
        is_local = False
    if not is_local:
        raise HTTPException(
            status_code=403,
            detail="Recruitment MVP APIs accept local requests only.",
        )


router = APIRouter(
    prefix="/api/v1",
    tags=["recruitment"],
    dependencies=[Depends(require_local_api_caller)],
)

_TERMINAL_APPLICATION_STAGES = {"HIRED", "REJECTED", "WITHDRAWN"}
_INTERVIEW_APPLICATION_STAGES = {
    "ASSESSMENT", "TECHNICAL_INTERVIEW", "MANAGERIAL_INTERVIEW", "HR_INTERVIEW"
}


def _allowed_application_stages(db: Session, application: Application) -> list[str]:
    if application.status == "CLOSED" or application.current_stage in _TERMINAL_APPLICATION_STAGES:
        return []
    terminal_choices = ["REJECTED", "WITHDRAWN"]
    if application.status == "ON_HOLD":
        return terminal_choices

    sequence = [stage.upper().replace(" ", "_") for stage in STAGE_SEQUENCE]
    try:
        next_stage = sequence[sequence.index(application.current_stage) + 1]
    except (ValueError, IndexError):
        next_stage = None
    if application.current_stage in _INTERVIEW_APPLICATION_STAGES:
        next_stage = None
    if next_stage == "HIRED":
        accepted_offer = db.scalar(
            select(func.count())
            .select_from(Offer)
            .where(
                Offer.application_id == application.application_id,
                Offer.status == "ACCEPTED",
            )
        )
        if not accepted_offer:
            next_stage = None
    return ([next_stage] if next_stage else []) + terminal_choices


def _approval_status(requisition: Requisition) -> str:
    if not requisition.approvals:
        return "NOT_SUBMITTED"
    latest_cycle = max(approval.approval_cycle for approval in requisition.approvals)
    decisions = [
        approval.decision
        for approval in requisition.approvals
        if approval.approval_cycle == latest_cycle
    ]
    if decisions and all(decision == "APPROVED" for decision in decisions):
        return "APPROVED"
    if "REJECTED" in decisions:
        return "REJECTED"
    if "RETURNED_FOR_REVISION" in decisions:
        return "RETURNED_FOR_REVISION"
    return "PENDING"


def _requisition_read(requisition: Requisition) -> RequisitionRead:
    return RequisitionRead(
        requisition_id=requisition.requisition_id,
        hiring_manager_id=requisition.hiring_manager_id,
        hiring_manager_name=requisition.hiring_manager.name,
        title=requisition.title,
        description=requisition.description,
        department=requisition.department,
        job_family=requisition.job_family,
        location=requisition.location,
        employment_type=requisition.employment_type,
        work_mode=requisition.work_mode,
        headcount=requisition.headcount,
        status=requisition.status,
        approval_status=_approval_status(requisition),
        min_salary=requisition.min_salary,
        max_salary=requisition.max_salary,
        currency_code=requisition.currency_code,
        compensation_period=requisition.compensation_period,
        opening_date=requisition.opening_date,
        closing_date=requisition.closing_date,
        created_at=requisition.created_at,
        updated_at=requisition.updated_at,
    )


def _candidate_read(candidate: Candidate) -> CandidateRead:
    return CandidateRead(
        candidate_id=candidate.candidate_id,
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        email=candidate.email,
        phone=candidate.phone,
        location=candidate.location,
        education_level=candidate.education_level,
        education_summary=candidate.education_summary,
        total_experience_months=candidate.total_experience_months,
        skills=sorted(item.skill.skill_name for item in candidate.skills),
        created_at=candidate.created_at,
    )


def _create_candidate_profile(
    db: Session,
    payload: CandidateCreate,
    *,
    actor_type: str,
    actor_id: str,
    actor_name_snapshot: str,
    reason: str,
) -> Candidate:
    candidate = Candidate(
        candidate_id=f"CAN-{uuid4().hex}",
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        phone=payload.phone,
        location=payload.location,
        education_level=payload.education_level,
        education_summary=payload.education_summary,
        total_experience_months=payload.total_experience_months,
    )
    db.add(candidate)
    db.flush()
    for skill_name in payload.skills:
        skill = db.scalar(select(Skill).where(Skill.skill_name == skill_name))
        if skill is None:
            skill = Skill(
                skill_id=f"SKL-{uuid4().hex}",
                skill_name=skill_name,
                active_status="ACTIVE",
            )
            db.add(skill)
            db.flush()
        db.add(
            CandidateSkill(
                candidate_skill_id=f"CSK-{uuid4().hex}",
                candidate_id=candidate.candidate_id,
                skill_id=skill.skill_id,
                proficiency_level="INTERMEDIATE",
                experience_months=0,
            )
        )
    db.add(
        AuditEvent(
            audit_event_id=f"AUDIT-{uuid4().hex}",
            event_type="CREATE",
            entity_type="CANDIDATE",
            entity_id=candidate.candidate_id,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name_snapshot=actor_name_snapshot,
            reason=reason,
        )
    )
    db.flush()
    return candidate


def _application_read(application: Application) -> dict:
    return {
        "application_id": application.application_id,
        "candidate_id": application.candidate_id,
        "candidate_name": f"{application.candidate.first_name} {application.candidate.last_name}",
        "candidate_email": application.candidate.email,
        "requisition_id": application.requisition_id,
        "requisition_title": application.requisition.title,
        "current_stage": application.current_stage,
        "status": application.status,
        "source_channel": application.source_channel,
        "applied_at": application.applied_at,
        "updated_at": application.updated_at,
    }


def _get_requisition(db: Session, requisition_id: str) -> Requisition:
    requisition = db.scalar(
        select(Requisition)
        .options(selectinload(Requisition.hiring_manager), selectinload(Requisition.approvals))
        .where(Requisition.requisition_id == requisition_id)
    )
    if requisition is None:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    return requisition


def _get_candidate(db: Session, candidate_id: str) -> Candidate:
    candidate = db.scalar(
        select(Candidate)
        .options(selectinload(Candidate.skills).selectinload(CandidateSkill.skill))
        .where(Candidate.candidate_id == candidate_id)
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return candidate


def _get_application(db: Session, application_id: str) -> Application:
    application = db.scalar(
        select(Application)
        .options(
            selectinload(Application.candidate),
            selectinload(Application.requisition),
            selectinload(Application.stage_history),
        )
        .where(Application.application_id == application_id)
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return application


def _has_scoped_requisition_permission(
    db: Session,
    user_id: str,
    permission_code: str,
    requisition: Requisition,
) -> bool:
    return db.scalar(
        select(Requisition.requisition_id).where(
            Requisition.requisition_id == requisition.requisition_id,
            _requisition_scope_filter(user_id, permission_code),
        )
    ) is not None


def _has_general_requisition_read(
    db: Session, user_id: str, requisition: Requisition
) -> bool:
    scope_matches = or_(
        UserRole.scope_type == "GLOBAL",
        (UserRole.scope_type == "DEPARTMENT")
        & (UserRole.scope_department == requisition.department),
        (UserRole.scope_type == "REQUISITION")
        & (UserRole.scope_requisition_id == requisition.requisition_id),
        (UserRole.scope_type == "RESOURCE")
        & (Role.role_code == "HIRING_MANAGER")
        & (User.hiring_manager_id == requisition.hiring_manager_id),
    )
    return db.scalar(
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .join(User, User.user_id == UserRole.user_id)
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
            Permission.permission_code == "requisitions.read",
            scope_matches,
        )
        .limit(1)
    ) is not None


def _requisition_scope_filter(user_id: str, permission_code: str):
    scope_matches = or_(
        UserRole.scope_type == "GLOBAL",
        (UserRole.scope_type == "DEPARTMENT")
        & (UserRole.scope_department == Requisition.department),
        (UserRole.scope_type == "REQUISITION")
        & (UserRole.scope_requisition_id == Requisition.requisition_id),
    )
    scoped_grant = exists(
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
            Permission.permission_code == permission_code,
            scope_matches,
        )
    )
    manager_grant = exists(
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .join(User, User.user_id == UserRole.user_id)
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            UserRole.scope_type == "RESOURCE",
            Role.role_code == "HIRING_MANAGER",
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
            Permission.permission_code == permission_code,
            User.hiring_manager_id == Requisition.hiring_manager_id,
        )
    )
    approver_grant = exists(
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .join(
            RequisitionApproval,
            RequisitionApproval.approver_id == UserRole.user_id,
        )
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            Role.role_code == "APPROVER",
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
            Permission.permission_code == permission_code,
            RequisitionApproval.requisition_id == Requisition.requisition_id,
        )
    )
    return or_(scoped_grant, manager_grant, approver_grant)


def _has_department_permission(
    db: Session, user_id: str, permission_code: str, department: str
) -> bool:
    return db.scalar(
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
            Permission.permission_code == permission_code,
            or_(
                UserRole.scope_type == "GLOBAL",
                (UserRole.scope_type == "DEPARTMENT")
                & (UserRole.scope_department == department),
            ),
        )
        .limit(1)
    ) is not None


def _approver_scope_matches(requisition: Requisition):
    return or_(
        UserRole.scope_type == "GLOBAL",
        (UserRole.scope_type == "DEPARTMENT")
        & (UserRole.scope_department == requisition.department),
        (UserRole.scope_type == "REQUISITION")
        & (UserRole.scope_requisition_id == requisition.requisition_id),
    )


def _eligible_approver(
    db: Session, approver_id: str, requisition: Requisition
) -> User | None:
    return db.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.user_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            User.user_id == approver_id,
            User.status == "ACTIVE",
            UserRole.revoked_at.is_(None),
            Role.role_code == "APPROVER",
            Role.is_active.is_(True),
            Permission.permission_code == "requisitions.approve",
            Permission.is_active.is_(True),
            _approver_scope_matches(requisition),
        )
        .limit(1)
    )


def _application_scope_filter(user_id: str):
    return Application.requisition_id.in_(
        select(Requisition.requisition_id).where(
            _requisition_scope_filter(user_id, "requisitions.read")
        )
    )


def _candidate_scope_filter(user_id: str):
    creator_access = exists(
        select(AuditEvent.audit_event_id).where(
            AuditEvent.entity_type == "CANDIDATE",
            AuditEvent.entity_id == Candidate.candidate_id,
            AuditEvent.event_type == "CREATE",
            AuditEvent.actor_type == "USER",
            AuditEvent.actor_id == user_id,
        )
    )
    global_reader = exists(
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
            UserRole.scope_type == "GLOBAL",
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
            Permission.permission_code == "candidates.read",
        )
    )
    return or_(
        Candidate.candidate_id.in_(
            select(Application.candidate_id).where(
                _application_scope_filter(user_id)
            )
        ),
        creator_access,
        global_reader,
    )


def _csv_safe(value: object) -> str:
    text_value = "" if value is None else str(value)
    if text_value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text_value
    return text_value


@router.get("/public/jobs")
def list_public_jobs(
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(Requisition).where(
        Requisition.status == "OPEN",
        or_(Requisition.closing_date.is_(None), Requisition.closing_date >= date.today()),
    )
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Requisition.title.ilike(pattern),
                Requisition.department.ilike(pattern),
                Requisition.location.ilike(pattern),
                Requisition.description.ilike(pattern),
            )
        )
    requisitions = db.scalars(
        statement.order_by(Requisition.created_at.desc()).limit(limit).offset(offset)
    )
    return [
        {
            "requisition_id": requisition.requisition_id,
            "title": requisition.title,
            "description": requisition.description,
            "department": requisition.department,
            "job_family": requisition.job_family,
            "location": requisition.location,
            "employment_type": requisition.employment_type,
            "work_mode": requisition.work_mode,
            "headcount": requisition.headcount,
            "min_salary": requisition.min_salary,
            "max_salary": requisition.max_salary,
            "currency_code": requisition.currency_code,
            "compensation_period": requisition.compensation_period,
            "closing_date": requisition.closing_date,
        }
        for requisition in requisitions
    ]


@router.post("/public/applications", status_code=status.HTTP_201_CREATED)
def submit_public_application(
    payload: PublicApplicationCreate,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    application_id = f"APP-{uuid4().hex}"
    try:
        with db.begin():
            requisition = db.scalar(
                select(Requisition)
                .where(Requisition.requisition_id == payload.requisition_id)
                .with_for_update()
            )
            if (
                requisition is None
                or requisition.status != "OPEN"
                or (
                    requisition.closing_date is not None
                    and requisition.closing_date < date.today()
                )
            ):
                raise HTTPException(
                    status_code=404,
                    detail="This job is no longer accepting applications.",
                )

            candidate = db.scalar(
                select(Candidate)
                .where(Candidate.email == payload.candidate.email)
                .with_for_update()
            )
            if candidate is None:
                candidate = _create_candidate_profile(
                    db,
                    payload.candidate,
                    actor_type="SERVICE",
                    actor_id="CAREER_PORTAL",
                    actor_name_snapshot="Candidate via career portal",
                    reason="Candidate profile created with applicant consent through the career portal.",
                )
            application = Application(
                application_id=application_id,
                candidate_id=candidate.candidate_id,
                requisition_id=requisition.requisition_id,
                source_channel="CAREER_SITE",
            )
            create_application(
                db,
                application,
                actor_id="CAREER_PORTAL",
                actor_name_snapshot="Candidate via career portal",
                reason="Application submitted through the candidate portal with applicant consent.",
                actor_type="SERVICE",
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "The application could not be submitted. It may already exist for this job; "
                "contact the recruiting team if you need help."
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "application_id": application_id,
        "message": "Your application has been submitted.",
    }


@router.get(
    "/reports/applications.csv",
    dependencies=[Depends(require_permission("applications.read"))],
)
def export_applications_csv(
    user: User = Depends(get_authenticated_user),
    limit: int = Query(default=5000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    applications = db.scalars(
        select(Application)
        .options(selectinload(Application.candidate), selectinload(Application.requisition))
        .where(_application_scope_filter(user.user_id))
        .order_by(Application.applied_at.desc())
        .limit(limit)
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "application_id",
            "candidate_name",
            "candidate_email",
            "requisition_id",
            "requisition_title",
            "stage",
            "status",
            "source_channel",
            "applied_at",
        ]
    )
    for application in applications:
        writer.writerow(
            _csv_safe(value)
            for value in (
                application.application_id,
                f"{application.candidate.first_name} {application.candidate.last_name}",
                application.candidate.email,
                application.requisition_id,
                application.requisition.title,
                application.current_stage,
                application.status,
                application.source_channel,
                application.applied_at.isoformat(),
            )
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="applications.csv"'},
    )


@router.get(
    "/reports/requisitions.csv",
    dependencies=[Depends(require_permission("requisitions.read"))],
)
def export_requisitions_csv(
    user: User = Depends(get_authenticated_user),
    limit: int = Query(default=5000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    requisitions = db.scalars(
        select(Requisition)
        .options(selectinload(Requisition.hiring_manager), selectinload(Requisition.approvals))
        .where(_requisition_scope_filter(user.user_id, "requisitions.read"))
        .order_by(Requisition.created_at.desc())
        .limit(limit)
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "requisition_id",
            "title",
            "department",
            "hiring_manager",
            "status",
            "approval_status",
            "opening_date",
            "closing_date",
        ]
    )
    for requisition in requisitions:
        writer.writerow(
            _csv_safe(value)
            for value in (
                requisition.requisition_id,
                requisition.title,
                requisition.department,
                requisition.hiring_manager.name,
                requisition.status,
                _approval_status(requisition),
                requisition.opening_date,
                requisition.closing_date,
            )
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="requisitions.csv"'},
    )


@router.get("/dashboard", dependencies=[Depends(require_permission("applications.read"))])
def dashboard(
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> dict:
    requisition_scope = _requisition_scope_filter(user.user_id, "requisitions.read")
    accessible_applications = Application.requisition_id.in_(
        select(Requisition.requisition_id).where(requisition_scope)
    )
    stage_counts = dict(
        db.execute(
            select(Application.current_stage, func.count())
            .where(accessible_applications)
            .group_by(Application.current_stage)
        ).all()
    )
    stages = [
        "APPLIED", "SCREENING", "ASSESSMENT", "TECHNICAL_INTERVIEW",
        "MANAGERIAL_INTERVIEW", "HR_INTERVIEW", "OFFER", "HIRED", "REJECTED", "WITHDRAWN",
    ]
    recent_applications = list(
        db.scalars(
            select(Application)
            .options(selectinload(Application.candidate), selectinload(Application.requisition))
            .where(accessible_applications)
            .order_by(Application.applied_at.desc())
            .limit(5)
        )
    )
    recent_requisitions = list(
        db.scalars(
            select(Requisition)
            .options(selectinload(Requisition.hiring_manager), selectinload(Requisition.approvals))
            .where(requisition_scope)
            .order_by(Requisition.created_at.desc())
            .limit(5)
        )
    )
    return {
        "total_requisitions": db.scalar(
            select(func.count()).select_from(Requisition).where(requisition_scope)
        ) or 0,
        "open_requisitions": db.scalar(
            select(func.count())
            .select_from(Requisition)
            .where(requisition_scope, Requisition.status == "OPEN")
        ) or 0,
        "total_candidates": db.scalar(
            select(func.count())
            .select_from(Candidate)
            .where(_candidate_scope_filter(user.user_id))
        ) or 0,
        "total_applications": db.scalar(
            select(func.count()).select_from(Application).where(accessible_applications)
        ) or 0,
        "applications_by_stage": {stage: stage_counts.get(stage, 0) for stage in stages},
        "recent_applications": [_application_read(item) for item in recent_applications],
        "recent_requisitions": [_requisition_read(item).model_dump(mode="json") for item in recent_requisitions],
    }


@router.get("/hiring-managers", response_model=None)
def list_hiring_managers(
    active_only: bool = False,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> list[HiringManager] | list[dict[str, str]]:
    permission_code = "requisitions.create" if active_only else "users.manage"
    if not has_permission(db, user.user_id, permission_code):
        raise HTTPException(status_code=403, detail="You are not authorized to view hiring managers.")
    statement = select(HiringManager)
    if active_only:
        statement = statement.where(HiringManager.active_status == "ACTIVE")
        return [
            {
                "hiring_manager_id": manager.hiring_manager_id,
                "name": manager.name,
                "department": manager.department,
                "active_status": manager.active_status,
            }
            for manager in db.scalars(
                statement.order_by(HiringManager.name, HiringManager.employee_code)
            )
        ]
    return list(db.scalars(statement.order_by(HiringManager.name, HiringManager.employee_code)))


@router.post(
    "/hiring-managers",
    response_model=HiringManagerRead,
    status_code=status.HTTP_201_CREATED,
)
def create_hiring_manager(
    payload: HiringManagerCreate,
    _user: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> HiringManager:
    manager_id = f"HM-{uuid4().hex}"
    manager = HiringManager(
        hiring_manager_id=manager_id,
        active_status="ACTIVE",
        **payload.model_dump(),
    )
    try:
        with db.begin():
            db.add(manager)
            db.flush()
            db.add(
                AuditEvent(
                    audit_event_id=f"AUDIT-{uuid4().hex}",
                    event_type="CREATE",
                    entity_type="HIRING_MANAGER",
                    entity_id=manager_id,
                    new_state="ACTIVE",
                    actor_type="USER",
                    actor_id=_user.user_id,
                    actor_name_snapshot=_user.display_name,
                    reason="Hiring manager created through the local MVP API.",
                )
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A hiring manager with this employee code or email already exists.",
        ) from exc
    return db.get(HiringManager, manager_id)


@router.get("/hiring-managers/{hiring_manager_id}", response_model=HiringManagerRead)
def hiring_manager_detail(
    hiring_manager_id: str,
    _user: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> HiringManager:
    manager = db.get(HiringManager, hiring_manager_id)
    if manager is None:
        raise HTTPException(status_code=404, detail="Hiring manager not found.")
    return manager


@router.get(
    "/requisitions",
    response_model=list[RequisitionRead],
    dependencies=[Depends(require_permission("requisitions.read"))],
)
def list_requisitions(
    search: str | None = None,
    requisition_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> list[RequisitionRead]:
    statement = select(Requisition).options(
        selectinload(Requisition.hiring_manager),
        selectinload(Requisition.approvals),
    ).where(_requisition_scope_filter(user.user_id, "requisitions.read"))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(Requisition.title.ilike(pattern), Requisition.department.ilike(pattern))
        )
    if requisition_status:
        statement = statement.where(Requisition.status == requisition_status.upper())
    items = db.scalars(
        statement.order_by(Requisition.created_at.desc()).limit(limit).offset(offset)
    )
    return [_requisition_read(item) for item in items]


@router.get(
    "/requisitions/{requisition_id}",
    response_model=RequisitionRead,
    dependencies=[Depends(require_permission("requisitions.read"))],
)
def requisition_detail(
    requisition_id: str,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> RequisitionRead:
    requisition = _get_requisition(db, requisition_id)
    if not _has_scoped_requisition_permission(
        db, user.user_id, "requisitions.read", requisition
    ):
        raise HTTPException(status_code=404, detail="Requisition not found.")
    return _requisition_read(requisition)


@router.post(
    "/requisitions",
    response_model=RequisitionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_requisition(
    payload: RequisitionCreate,
    _user: User = Depends(require_permission("requisitions.create")),
    db: Session = Depends(get_db),
) -> RequisitionRead:
    requisition_id = f"REQ-{uuid4().hex}"
    try:
        with db.begin():
            manager = db.get(HiringManager, payload.hiring_manager_id)
            if manager is None or manager.active_status != "ACTIVE":
                raise HTTPException(status_code=422, detail="An active hiring manager is required.")
            if not _has_department_permission(
                db, _user.user_id, "requisitions.create", payload.department
            ):
                raise HTTPException(
                    status_code=403,
                    detail="You are not authorized to create requisitions for this department.",
                )
            requisition = Requisition(
                requisition_id=requisition_id,
                status="DRAFT",
                **payload.model_dump(),
            )
            db.add(requisition)
            db.flush()
            db.add(
                AuditEvent(
                    audit_event_id=f"AUDIT-{uuid4().hex}",
                    event_type="CREATE",
                    entity_type="REQUISITION",
                    entity_id=requisition_id,
                    new_state="DRAFT",
                    actor_type="USER",
                    actor_id=_user.user_id,
                    actor_name_snapshot=_user.display_name,
                    reason="Created as draft; approval is required before opening.",
                )
            )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Requisition could not be created.") from exc
    return _requisition_read(_get_requisition(db, requisition_id))


@router.put(
    "/requisitions/{requisition_id}",
    response_model=RequisitionRead,
)
def update_requisition(
    requisition_id: str,
    payload: RequisitionUpdate,
    _user: User = Depends(require_permission("requisitions.update")),
    db: Session = Depends(get_db),
) -> RequisitionRead:
    updates = payload.model_dump(exclude_unset=True)
    reason = updates.pop("reason", None)
    if not updates:
        raise HTTPException(status_code=422, detail="At least one requisition field must be updated.")
    try:
        with db.begin():
            requisition = db.scalar(
                select(Requisition)
                .where(Requisition.requisition_id == requisition_id)
                .with_for_update()
            )
            if requisition is None:
                raise HTTPException(status_code=404, detail="Requisition not found.")
            if not _has_scoped_requisition_permission(
                db, _user.user_id, "requisitions.update", requisition
            ):
                raise HTTPException(status_code=403, detail="You are not authorized for this requisition.")
            if requisition.status not in {"DRAFT", "PENDING_APPROVAL"}:
                raise HTTPException(
                    status_code=409,
                    detail="Only draft or pending-approval requisitions can be edited.",
                )
            old_values = {key: getattr(requisition, key) for key in updates}
            for key, value in updates.items():
                if value is None and key not in {"description", "min_salary", "max_salary", "currency_code", "compensation_period", "closing_date"}:
                    raise HTTPException(status_code=422, detail=f"{key} cannot be empty.")
                setattr(requisition, key, value)
            if (
                requisition.min_salary is not None
                and requisition.max_salary is not None
                and requisition.min_salary > requisition.max_salary
            ):
                raise HTTPException(status_code=422, detail="min_salary must not exceed max_salary.")
            if requisition.closing_date and requisition.closing_date < requisition.opening_date:
                raise HTTPException(status_code=422, detail="closing_date must be on or after opening_date.")
            requisition.updated_at = datetime.now(timezone.utc)
            db.add(
                AuditEvent(
                    audit_event_id=f"AUDIT-{uuid4().hex}",
                    event_type="UPDATE",
                    entity_type="REQUISITION",
                    entity_id=requisition_id,
                    actor_type="USER",
                    actor_id=_user.user_id,
                    actor_name_snapshot=_user.display_name,
                    reason=(reason or "Updated requisition details through the MVP API").strip(),
                    payload={
                        "before": {key: str(value) if value is not None else None for key, value in old_values.items()},
                        "after": {key: str(value) if value is not None else None for key, value in updates.items()},
                    },
                )
            )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Requisition update conflicts with existing data.") from exc
    return _requisition_read(_get_requisition(db, requisition_id))


@router.get("/requisitions/{requisition_id}/approvers")
def list_eligible_approvers(
    requisition_id: str,
    user: User = Depends(require_permission("requisitions.update")),
    db: Session = Depends(get_db),
) -> list[dict[str, str]]:
    requisition = db.get(Requisition, requisition_id)
    if requisition is None:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    if not _has_scoped_requisition_permission(
        db, user.user_id, "requisitions.update", requisition
    ):
        raise HTTPException(status_code=403, detail="You are not authorized for this requisition.")
    approvers = db.scalars(
        select(User)
        .join(UserRole, UserRole.user_id == User.user_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            User.status == "ACTIVE",
            UserRole.revoked_at.is_(None),
            Role.role_code == "APPROVER",
            Role.is_active.is_(True),
            Permission.permission_code == "requisitions.approve",
            Permission.is_active.is_(True),
            _approver_scope_matches(requisition),
        )
        .distinct()
        .order_by(User.display_name)
    )
    return [
        {"user_id": approver.user_id, "display_name": approver.display_name}
        for approver in approvers
        if approver.user_id != user.user_id
        and approver.hiring_manager_id != requisition.hiring_manager_id
    ]


@router.post("/requisitions/{requisition_id}/submit-for-approval")
def submit_requisition_for_approval(
    requisition_id: str,
    payload: RequisitionApprovalSubmission,
    user: User = Depends(require_permission("requisitions.update")),
    db: Session = Depends(get_db),
) -> list[dict]:
    try:
        with db.begin():
            requisition = db.scalar(
                select(Requisition)
                .where(Requisition.requisition_id == requisition_id)
                .with_for_update()
            )
            if requisition is None:
                raise HTTPException(status_code=404, detail="Requisition not found.")
            if not _has_scoped_requisition_permission(
                db, user.user_id, "requisitions.update", requisition
            ):
                raise HTTPException(status_code=403, detail="You are not authorized for this requisition.")
            if requisition.status != "DRAFT":
                raise HTTPException(status_code=409, detail="Only draft requisitions can be submitted.")

            if requisition.hiring_manager_id == user.hiring_manager_id:
                raise HTTPException(
                    status_code=409,
                    detail="A hiring manager cannot approve their own requisition.",
                )
            previous_cycle = db.scalar(
                select(func.max(RequisitionApproval.approval_cycle)).where(
                    RequisitionApproval.requisition_id == requisition_id
                )
            )
            previous_by_stage = {}
            if previous_cycle is not None:
                previous_by_stage = {
                    approval.approval_stage: approval
                    for approval in db.scalars(
                        select(RequisitionApproval).where(
                            RequisitionApproval.requisition_id == requisition_id,
                            RequisitionApproval.approval_cycle == previous_cycle,
                        )
                    )
                }
            cycle = (previous_cycle or 0) + 1
            for assignment in payload.approvals:
                approver = _eligible_approver(db, assignment.approver_id, requisition)
                if approver is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Each assigned approver must be active and authorized for this requisition.",
                    )
                if (
                    approver.user_id == user.user_id
                    or approver.hiring_manager_id == requisition.hiring_manager_id
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="The requester and hiring manager cannot approve this requisition.",
                    )
                db.add(
                    RequisitionApproval(
                        requisition_approval_id=f"RAPP-{uuid4().hex}",
                        requisition_id=requisition_id,
                        approver_id=approver.user_id,
                        approval_cycle=cycle,
                        approval_sequence=assignment.approval_sequence,
                        approval_stage=assignment.approval_stage,
                        decision="PENDING",
                        supersedes_requisition_approval_id=(
                            previous_by_stage[assignment.approval_stage].requisition_approval_id
                            if assignment.approval_stage in previous_by_stage
                            else None
                        ),
                    )
                )
            transition_requisition(
                db,
                requisition_id,
                "PENDING_APPROVAL",
                actor_id=user.user_id,
                actor_name_snapshot=user.display_name,
                reason=payload.reason,
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _requisition_approvals_read(db, requisition_id)


@router.get("/requisitions/{requisition_id}/approvals")
def list_requisition_approvals(
    requisition_id: str,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    requisition = db.get(Requisition, requisition_id)
    if requisition is None:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    can_read_all = _has_general_requisition_read(db, user.user_id, requisition)
    if not can_read_all:
        is_assigned_approver = db.scalar(
            select(RequisitionApproval.requisition_approval_id).where(
                RequisitionApproval.requisition_id == requisition_id,
                RequisitionApproval.approver_id == user.user_id,
            ).limit(1)
        )
        if (
            not is_assigned_approver
            or _eligible_approver(db, user.user_id, requisition) is None
        ):
            raise HTTPException(status_code=403, detail="You are not authorized for these approvals.")
    return _requisition_approvals_read(
        db,
        requisition_id,
        approver_id=None if can_read_all else user.user_id,
    )


def _requisition_approvals_read(
    db: Session, requisition_id: str, *, approver_id: str | None = None
) -> list[dict]:
    statement = select(RequisitionApproval).where(
        RequisitionApproval.requisition_id == requisition_id
    )
    if approver_id is not None:
        statement = statement.where(RequisitionApproval.approver_id == approver_id)
    approvals = db.scalars(
        statement.order_by(
            RequisitionApproval.approval_cycle, RequisitionApproval.approval_sequence
        )
    )
    result = []
    for approval in approvals:
        approver = db.get(User, approval.approver_id)
        result.append({
            "requisition_approval_id": approval.requisition_approval_id,
            "requisition_id": approval.requisition_id,
            "approver_id": approval.approver_id,
            "approver_name": approver.display_name if approver else "Unavailable account",
            "approval_cycle": approval.approval_cycle,
            "approval_sequence": approval.approval_sequence,
            "approval_stage": approval.approval_stage,
            "decision": approval.decision,
            "comments": approval.comments,
            "requested_at": approval.requested_at,
            "decided_at": approval.decided_at,
        })
    return result


@router.get("/approvals")
def list_my_pending_approvals(
    user: User = Depends(require_permission("requisitions.approve")),
    db: Session = Depends(get_db),
) -> list[dict]:
    records = db.execute(
        select(RequisitionApproval, Requisition.title)
        .join(Requisition, Requisition.requisition_id == RequisitionApproval.requisition_id)
        .where(
            RequisitionApproval.approver_id == user.user_id,
            RequisitionApproval.decision == "PENDING",
            Requisition.status == "PENDING_APPROVAL",
        )
        .order_by(RequisitionApproval.requested_at, RequisitionApproval.approval_sequence)
    )
    pending = []
    for approval, title in records:
        latest_cycle = db.scalar(
            select(func.max(RequisitionApproval.approval_cycle)).where(
                RequisitionApproval.requisition_id == approval.requisition_id
            )
        )
        requisition = db.get(Requisition, approval.requisition_id)
        if (
            approval.approval_cycle == latest_cycle
            and requisition is not None
            and _eligible_approver(db, user.user_id, requisition) is not None
        ):
            earlier_pending = db.scalar(
                select(RequisitionApproval.requisition_approval_id)
                .where(
                    RequisitionApproval.requisition_id == approval.requisition_id,
                    RequisitionApproval.approval_cycle == approval.approval_cycle,
                    RequisitionApproval.approval_sequence < approval.approval_sequence,
                    RequisitionApproval.decision != "APPROVED",
                )
                .limit(1)
            )
            if earlier_pending is not None:
                continue
            pending.append(
                {
                    "requisition_approval_id": approval.requisition_approval_id,
                    "requisition_id": approval.requisition_id,
                    "requisition_title": title,
                    "approval_stage": approval.approval_stage,
                    "approval_sequence": approval.approval_sequence,
                    "approval_cycle": approval.approval_cycle,
                    "requested_at": approval.requested_at,
                }
            )
    return pending


@router.post("/requisition-approvals/{approval_id}/decision")
def decide_requisition_approval_api(
    approval_id: str,
    payload: RequisitionApprovalDecision,
    user: User = Depends(require_permission("requisitions.approve")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        with db.begin():
            approval = db.scalar(
                select(RequisitionApproval)
                .where(RequisitionApproval.requisition_approval_id == approval_id)
                .with_for_update()
            )
            if approval is None:
                raise HTTPException(status_code=404, detail="Approval not found.")
            requisition = db.get(Requisition, approval.requisition_id)
            if requisition is None:
                raise HTTPException(status_code=404, detail="Approval not found.")
            if requisition.status != "PENDING_APPROVAL":
                raise HTTPException(
                    status_code=409,
                    detail="Only approvals in the active pending cycle can be decided.",
                )
            latest_cycle = db.scalar(
                select(func.max(RequisitionApproval.approval_cycle)).where(
                    RequisitionApproval.requisition_id == requisition.requisition_id
                )
            )
            if approval.approval_cycle != latest_cycle:
                raise HTTPException(
                    status_code=409,
                    detail="This approval belongs to a superseded cycle.",
                )
            unfinished_previous = db.scalar(
                select(RequisitionApproval.requisition_approval_id)
                .where(
                    RequisitionApproval.requisition_id == requisition.requisition_id,
                    RequisitionApproval.approval_cycle == approval.approval_cycle,
                    RequisitionApproval.approval_sequence < approval.approval_sequence,
                    RequisitionApproval.decision != "APPROVED",
                )
                .limit(1)
            )
            if unfinished_previous is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Earlier approval stages must be approved first.",
                )
            if _eligible_approver(db, user.user_id, requisition) is None:
                raise HTTPException(
                    status_code=403,
                    detail="You are not authorized to decide approvals for this requisition.",
                )
            if user.hiring_manager_id == requisition.hiring_manager_id:
                raise HTTPException(
                    status_code=403,
                    detail="A hiring manager cannot approve their own requisition.",
                )
            created_by = db.scalar(
                select(AuditEvent.actor_id)
                .where(
                    AuditEvent.entity_type == "REQUISITION",
                    AuditEvent.entity_id == requisition.requisition_id,
                    AuditEvent.event_type == "CREATE",
                )
                .order_by(AuditEvent.occurred_at)
                .limit(1)
            )
            if created_by == user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="The requisition requester cannot approve their own requisition.",
                )
            decided = decide_requisition_approval(
                db,
                approval_id,
                payload.decision,
                actor_id=user.user_id,
                actor_name_snapshot=user.display_name,
                comments=payload.comments,
            )
    except ValueError as exc:
        message = str(exc)
        code = 404 if "does not exist" in message else 409
        raise HTTPException(status_code=code, detail=message) from exc
    return {
        "requisition_approval_id": decided.requisition_approval_id,
        "requisition_id": decided.requisition_id,
        "decision": decided.decision,
        "comments": decided.comments,
        "decided_at": decided.decided_at,
    }


@router.post("/requisitions/{requisition_id}/return-to-draft")
def return_requisition_to_draft(
    requisition_id: str,
    payload: RequisitionLifecycleReason,
    user: User = Depends(require_permission("requisitions.update")),
    db: Session = Depends(get_db),
) -> RequisitionRead:
    try:
        with db.begin():
            requisition = db.get(Requisition, requisition_id)
            if requisition is None:
                raise HTTPException(status_code=404, detail="Requisition not found.")
            if not _has_scoped_requisition_permission(
                db, user.user_id, "requisitions.update", requisition
            ):
                raise HTTPException(status_code=403, detail="You are not authorized for this requisition.")
            latest_cycle = db.scalar(
                select(func.max(RequisitionApproval.approval_cycle)).where(
                    RequisitionApproval.requisition_id == requisition_id
                )
            )
            if latest_cycle is None:
                raise HTTPException(status_code=409, detail="This requisition has no approval cycle.")
            decisions = list(
                db.scalars(
                    select(RequisitionApproval.decision).where(
                        RequisitionApproval.requisition_id == requisition_id,
                        RequisitionApproval.approval_cycle == latest_cycle,
                    )
                )
            )
            if not any(
                decision in {"REJECTED", "RETURNED_FOR_REVISION"}
                for decision in decisions
            ):
                raise HTTPException(
                    status_code=409,
                    detail="A requisition can return to draft only after rejection or a revision request.",
                )
            transition_requisition(
                db,
                requisition_id,
                "DRAFT",
                actor_id=user.user_id,
                actor_name_snapshot=user.display_name,
                reason=payload.reason,
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _requisition_read(_get_requisition(db, requisition_id))


@router.post("/requisitions/{requisition_id}/open")
def open_requisition(
    requisition_id: str,
    payload: RequisitionLifecycleReason,
    user: User = Depends(require_permission("requisitions.update")),
    db: Session = Depends(get_db),
) -> RequisitionRead:
    try:
        with db.begin():
            requisition = db.get(Requisition, requisition_id)
            if requisition is None:
                raise HTTPException(status_code=404, detail="Requisition not found.")
            if not _has_scoped_requisition_permission(
                db, user.user_id, "requisitions.update", requisition
            ):
                raise HTTPException(status_code=403, detail="You are not authorized for this requisition.")
            latest_cycle = db.scalar(
                select(func.max(RequisitionApproval.approval_cycle)).where(
                    RequisitionApproval.requisition_id == requisition_id
                )
            )
            stages = []
            if latest_cycle is not None:
                stages = list(
                    db.scalars(
                        select(RequisitionApproval.approval_stage).where(
                            RequisitionApproval.requisition_id == requisition_id,
                            RequisitionApproval.approval_cycle == latest_cycle,
                        )
                    )
                )
            transition_requisition(
                db,
                requisition_id,
                "OPEN",
                required_approval_stages=stages,
                actor_id=user.user_id,
                actor_name_snapshot=user.display_name,
                reason=payload.reason,
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _requisition_read(_get_requisition(db, requisition_id))


@router.get(
    "/candidates",
    response_model=list[CandidateRead],
    dependencies=[Depends(require_permission("candidates.read"))],
)
def list_candidates(
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> list[CandidateRead]:
    statement = select(Candidate).options(
        selectinload(Candidate.skills).selectinload(CandidateSkill.skill)
    ).where(_candidate_scope_filter(user.user_id))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Candidate.first_name.ilike(pattern),
                Candidate.last_name.ilike(pattern),
                Candidate.email.ilike(pattern),
            )
        )
    items = db.scalars(
        statement.order_by(Candidate.created_at.desc()).limit(limit).offset(offset)
    )
    return [_candidate_read(item) for item in items]


@router.get(
    "/candidates/{candidate_id}",
    response_model=CandidateRead,
    dependencies=[Depends(require_permission("candidates.read"))],
)
def candidate_detail(
    candidate_id: str,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> CandidateRead:
    if not db.scalar(
        select(Candidate.candidate_id).where(
            Candidate.candidate_id == candidate_id,
            _candidate_scope_filter(user.user_id),
        )
    ):
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return _candidate_read(_get_candidate(db, candidate_id))


@router.post(
    "/candidates",
    response_model=CandidateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate(
    payload: CandidateCreate,
    user: User = Depends(require_permission("candidates.create")),
    db: Session = Depends(get_db),
) -> CandidateRead:
    try:
        with db.begin():
            candidate = _create_candidate_profile(
                db,
                payload,
                actor_type="USER",
                actor_id=user.user_id,
                actor_name_snapshot=user.display_name,
                reason="Candidate record created through the recruiter API.",
            )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A candidate with this email already exists.") from exc
    return _candidate_read(_get_candidate(db, candidate.candidate_id))


@router.get(
    "/applications",
)
def list_applications(
    search: str | None = None,
    application_stage: str | None = Query(default=None, alias="stage"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_permission("applications.read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(Application).options(
        selectinload(Application.candidate),
        selectinload(Application.requisition),
    ).where(_application_scope_filter(user.user_id))
    if application_stage:
        statement = statement.where(Application.current_stage == application_stage.upper())
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.join(Candidate).join(Requisition).where(
            or_(
                Candidate.first_name.ilike(pattern),
                Candidate.last_name.ilike(pattern),
                Candidate.email.ilike(pattern),
                Requisition.title.ilike(pattern),
            )
        )
    items = db.scalars(
        statement.order_by(Application.applied_at.desc()).limit(limit).offset(offset)
    )
    return [_application_read(item) for item in items]


@router.get(
    "/applications/{application_id}",
)
def application_detail(
    application_id: str,
    user: User = Depends(require_permission("applications.read")),
    db: Session = Depends(get_db),
) -> dict:
    if not db.scalar(
        select(Application.application_id).where(
            Application.application_id == application_id,
            _application_scope_filter(user.user_id),
        )
    ):
        raise HTTPException(status_code=404, detail="Application not found.")
    application = _get_application(db, application_id)
    return {
        **_application_read(application),
        "allowed_next_stages": _allowed_application_stages(db, application),
        "stage_history": [
            {
                "previous_stage": item.previous_stage,
                "new_stage": item.new_stage,
                "previous_status": item.previous_status,
                "new_status": item.new_status,
                "actor_name_snapshot": item.actor_name_snapshot,
                "reason": item.reason,
                "occurred_at": item.occurred_at,
            }
            for item in sorted(application.stage_history, key=lambda history: history.history_sequence)
        ],
    }


@router.post(
    "/applications",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
)
def submit_application(
    payload: ApplicationCreate,
    user: User = Depends(require_permission("applications.manage")),
    db: Session = Depends(get_db),
) -> ApplicationRead:
    application_id = f"APP-{uuid4().hex}"
    try:
        with db.begin():
            candidate = db.get(Candidate, payload.candidate_id)
            if candidate is None:
                raise HTTPException(status_code=404, detail="Candidate not found.")
            if not db.scalar(
                select(Candidate.candidate_id).where(
                    Candidate.candidate_id == payload.candidate_id,
                    _candidate_scope_filter(user.user_id),
                )
            ):
                raise HTTPException(status_code=404, detail="Candidate not found.")
            requisition = db.get(Requisition, payload.requisition_id)
            if requisition is None:
                raise HTTPException(status_code=404, detail="Requisition not found.")
            if not _has_scoped_requisition_permission(
                db, user.user_id, "applications.manage", requisition
            ):
                raise HTTPException(status_code=404, detail="Requisition not found.")
            application = Application(
                application_id=application_id,
                candidate_id=payload.candidate_id,
                requisition_id=payload.requisition_id,
                source_channel=payload.source_channel,
                source_detail=payload.source_detail,
            )
            create_application(
                db,
                application,
                actor_id=user.user_id,
                actor_name_snapshot=user.display_name,
                reason="Application submitted through the MVP API.",
                actor_type="USER",
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Application conflicts with an existing application or requisition.",
        ) from exc
    return ApplicationRead(**_application_read(_get_application(db, application_id)))


@router.post(
    "/applications/{application_id}/transition",
)
def change_application_stage(
    application_id: str,
    payload: ApplicationTransition,
    user: User = Depends(require_permission("applications.transition")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        with db.begin():
            application_scope = db.scalar(
                select(Application).where(
                    Application.application_id == application_id,
                    _application_scope_filter(user.user_id),
                )
            )
            if application_scope is None:
                raise HTTPException(status_code=404, detail="Application not found.")
            requisition = db.get(Requisition, application_scope.requisition_id)
            if requisition is None or not _has_scoped_requisition_permission(
                db, user.user_id, "applications.transition", requisition
            ):
                raise HTTPException(status_code=404, detail="Application not found.")
            application = transition_application(
                db,
                application_id,
                actor_id=user.user_id,
                actor_name_snapshot=user.display_name,
                reason=payload.reason,
                new_stage=payload.new_stage,
                new_status=payload.new_status,
                actor_type="USER",
            )
            changed_id = application.application_id
    except ValueError as exc:
        message = str(exc)
        code = 404 if "does not exist" in message else 409
        raise HTTPException(status_code=code, detail=message) from exc
    updated = _get_application(db, changed_id)
    return {
        **_application_read(updated),
        "allowed_next_stages": _allowed_application_stages(db, updated),
        "stage_history": [
            {
                "previous_stage": item.previous_stage,
                "new_stage": item.new_stage,
                "previous_status": item.previous_status,
                "new_status": item.new_status,
                "actor_name_snapshot": item.actor_name_snapshot,
                "reason": item.reason,
                "occurred_at": item.occurred_at,
            }
            for item in sorted(updated.stage_history, key=lambda history: history.history_sequence)
        ],
    }
