from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.api.dependencies.auth import require_permission
from src.database.session import get_db
from src.models import Role, User, UserRole
from src.schemas.user_schema import RoleRead, StaffAccountCreate, StaffAccountRead
from src.services.account_service import (
    AccountAuthorizationError,
    AccountConflictError,
    AccountProvisioningError,
    RoleGrantRequest,
    provision_user,
)

router = APIRouter(prefix="/api/v1", tags=["user administration"])


def _read_user(user: User) -> StaffAccountRead:
    return StaffAccountRead(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        hiring_manager_id=user.hiring_manager_id,
        interviewer_id=user.interviewer_id,
        role_grants=[
            {
                "role_code": grant.role.role_code,
                "scope_type": grant.scope_type,
                "scope_department": grant.scope_department,
                "scope_requisition_id": grant.scope_requisition_id,
            }
            for grant in user.role_grants
            if grant.revoked_at is None
        ],
    )


@router.get("/roles", response_model=list[RoleRead])
def list_roles(
    _actor: User = Depends(require_permission("roles.manage")),
    db: Session = Depends(get_db),
) -> list[RoleRead]:
    roles = db.scalars(
        select(Role)
        .where(Role.is_system.is_(True), Role.is_active.is_(True))
        .order_by(Role.role_code)
    )
    return [
        RoleRead(
            role_id=role.role_id,
            role_code=role.role_code,
            name=role.name,
            description=role.description,
        )
        for role in roles
    ]


@router.get("/users", response_model=list[StaffAccountRead])
def list_users(
    _actor: User = Depends(require_permission("users.manage")),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[StaffAccountRead]:
    users = db.scalars(
        select(User)
        .options(selectinload(User.role_grants).selectinload(UserRole.role))
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_read_user(user) for user in users]


@router.post(
    "/users",
    response_model=StaffAccountRead,
    status_code=status.HTTP_201_CREATED,
)
def create_staff_account(
    payload: StaffAccountCreate,
    actor: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> StaffAccountRead:
    role_grants = [
        RoleGrantRequest(
            role_code=grant.role_code,
            scope_type=grant.scope_type,
            scope_department=grant.scope_department,
            scope_requisition_id=grant.scope_requisition_id,
        )
        for grant in payload.role_grants
    ]
    try:
        with db.begin():
            user = provision_user(
                db,
                actor_user_id=actor.user_id,
                email=payload.email,
                display_name=payload.display_name,
                hiring_manager_id=payload.hiring_manager_id,
                interviewer_id=payload.interviewer_id,
                role_grants=role_grants,
            )
            user_id = user.user_id
    except AccountAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except AccountConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except AccountProvisioningError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    user = db.scalar(
        select(User)
        .options(selectinload(User.role_grants).selectinload(UserRole.role))
        .where(User.user_id == user_id)
    )
    if user is None:
        raise HTTPException(status_code=500, detail="Provisioned account could not be retrieved.")
    return _read_user(user)
