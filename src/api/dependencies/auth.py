from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.database.session import get_db
from src.models import Permission, Role, RolePermission, User, UserRole
from src.services.access_token_service import (
    AccessTokenConfigurationError,
    AccessTokenService,
    AuthenticatedUserContext,
    InvalidAccessToken,
)

_bearer = HTTPBearer(auto_error=False)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def get_authenticated_user_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AuthenticatedUserContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return AccessTokenService(_settings(request)).verify_access_token(
            db, credentials.credentials
        )
    except AccessTokenConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except InvalidAccessToken:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_authenticated_user(
    context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, context.user_id)
    if user is None or user.status != "ACTIVE":
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    db.commit()
    return user


def require_permission(permission_code: str) -> Callable:
    def dependency(
        user: User = Depends(get_authenticated_user),
        db: Session = Depends(get_db),
    ) -> User:
        grant_id = db.scalar(
            select(UserRole.user_role_id)
            .join(Role, Role.role_id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.role_id)
            .join(
                Permission,
                Permission.permission_id == RolePermission.permission_id,
            )
            .where(
                UserRole.user_id == user.user_id,
                UserRole.revoked_at.is_(None),
                Role.is_active.is_(True),
                Permission.is_active.is_(True),
                Permission.permission_code == permission_code,
            )
            .limit(1)
        )
        if grant_id is None:
            raise HTTPException(
                status_code=403,
                detail="You are not authorized to perform this operation.",
            )
        db.commit()
        return user

    return dependency


def has_permission(db: Session, user_id: str, permission_code: str) -> bool:
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
        )
        .limit(1)
    ) is not None
