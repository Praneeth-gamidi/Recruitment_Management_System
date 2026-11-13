from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.dependencies.auth import get_authenticated_user, get_authenticated_user_context
from src.core.config import Settings
from src.database.session import get_db
from src.models import RefreshToken, Role, User, UserRole
from src.services.access_token_service import (
    AccessTokenConfigurationError,
    AccessTokenService,
    AuthenticatedUserContext,
)
from src.services.account_service import normalize_email
from src.services.password_security import verify_password
from src.services.refresh_token_service import (
    InvalidRefreshToken,
    create_refresh_token_family,
    revoke_refresh_token_family,
    rotate_refresh_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
_AUTH_FAILURE = "Invalid email or password."
_COOKIE_NAME = "rms_refresh"
_CSRF_COOKIE = "rms_csrf"
_CSRF_HEADER = "X-CSRF-Token"
_LOGIN_ATTEMPT_LIMIT = 5
_LOGIN_LOCKOUT = timedelta(minutes=15)
_GENERIC_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$invalid"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        try:
            return normalize_email(value)
        except ValueError:
            raise ValueError("A valid email address is required.") from None


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _set_refresh_cookies(
    response: Response,
    *,
    refresh_token: str,
    csrf_token: str,
    settings: Settings,
) -> None:
    secure = settings.environment.lower() not in {"development", "test", "local"}
    response.set_cookie(
        _COOKIE_NAME,
        refresh_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/api/v1/auth",
        max_age=settings.refresh_token_lifetime_days * 86400,
    )
    response.set_cookie(
        _CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/api/v1/auth",
        max_age=settings.refresh_token_lifetime_days * 86400,
    )


def _require_same_origin_csrf(request: Request) -> None:
    origin = request.headers.get("origin")
    csrf_cookie = request.cookies.get(_CSRF_COOKIE)
    csrf_header = request.headers.get(_CSRF_HEADER)
    if (
        not origin
        or urlsplit(origin).netloc.lower() != request.url.netloc.lower()
        or not csrf_cookie
        or not csrf_header
        or not secrets.compare_digest(csrf_cookie, csrf_header)
    ):
        raise HTTPException(status_code=403, detail="Request origin validation failed.")


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    authenticated_user: User | None = None

    with db.begin():
        user = db.scalar(
            select(User).where(User.email == payload.email).with_for_update()
        )
        matched_password = verify_password(
            payload.password,
            user.password_hash
            if user is not None and user.password_hash
            else _GENERIC_HASH,
        )
        if user is not None:
            lock_expired = (
                user.locked_until is not None
                and _as_utc(user.locked_until) <= now
            )
            if lock_expired:
                user.locked_until = None
                user.failed_login_count = 0
                if user.status == "LOCKED":
                    user.status = "ACTIVE"

            if (
                user.status == "ACTIVE"
                and (user.locked_until is None or _as_utc(user.locked_until) <= now)
                and matched_password
            ):
                user.failed_login_count = 0
                user.locked_until = None
                user.last_login_at = now
                authenticated_user = user
            elif user.status == "ACTIVE":
                user.failed_login_count += 1
                if user.failed_login_count >= _LOGIN_ATTEMPT_LIMIT:
                    user.status = "LOCKED"
                    user.locked_until = now + _LOGIN_LOCKOUT

    if authenticated_user is None:
        raise HTTPException(status_code=401, detail=_AUTH_FAILURE)

    csrf_token = secrets.token_urlsafe(32)
    try:
        token_service = AccessTokenService(_settings(request))
        access_token = token_service.create_access_token(db, authenticated_user)
        db.commit()
        if db.in_transaction():
            db.rollback()
        refresh_grant = create_refresh_token_family(db, authenticated_user)
    except AccessTokenConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from None

    _set_refresh_cookies(
        response,
        refresh_token=refresh_grant.raw_token,
        csrf_token=csrf_token,
        settings=_settings(request),
    )
    return {
        "access_token": access_token.encoded_token,
        "token_type": access_token.token_type,
        "expires_in": access_token.expires_in,
        "csrf_token": csrf_token,
    }


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> RefreshResponse:
    _require_same_origin_csrf(request)
    raw_token = request.cookies.get(_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials.")
    try:
        rotation = rotate_refresh_token(db, raw_token)
        user = db.get(User, rotation.user_id)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials.",
            )
        access_token = AccessTokenService(_settings(request)).create_access_token(db, user)
        db.commit()
    except InvalidRefreshToken:
        response.delete_cookie(_COOKIE_NAME, path="/api/v1/auth")
        response.delete_cookie(_CSRF_COOKIE, path="/api/v1/auth")
        raise HTTPException(status_code=401, detail="Invalid authentication credentials.") from None
    except AccessTokenConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from None

    csrf_token = request.cookies[_CSRF_COOKIE]
    _set_refresh_cookies(
        response,
        refresh_token=rotation.grant.raw_token,
        csrf_token=csrf_token,
        settings=_settings(request),
    )
    return RefreshResponse(
        access_token=access_token.encoded_token,
        token_type=access_token.token_type,
        expires_in=access_token.expires_in,
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    context: AuthenticatedUserContext = Depends(get_authenticated_user_context),
    db: Session = Depends(get_db),
) -> Response:
    _require_same_origin_csrf(request)
    raw_token = request.cookies.get(_COOKIE_NAME)
    if raw_token:
        import hashlib

        try:
            digest = hashlib.sha256(raw_token.encode("ascii")).digest()
        except UnicodeEncodeError:
            digest = b""
        token = db.scalar(
            select(RefreshToken).where(RefreshToken.token_digest == digest)
        )
        db.commit()
        if token is not None:
            try:
                revoke_refresh_token_family(db, context, token.family_id)
            except InvalidRefreshToken:
                db.rollback()
    response.delete_cookie(_COOKIE_NAME, path="/api/v1/auth")
    response.delete_cookie(_CSRF_COOKIE, path="/api/v1/auth")
    response.status_code = 204
    return response


@router.get("/me")
def current_user(
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    role_codes = db.scalars(
        select(Role.role_code)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(
            UserRole.user_id == user.user_id,
            UserRole.revoked_at.is_(None),
            Role.is_active.is_(True),
        )
        .distinct()
        .order_by(Role.role_code)
    )
    return {
        "user_id": user.user_id,
        "email": user.email,
        "display_name": user.display_name,
        "status": user.status,
        "roles": list(role_codes),
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
