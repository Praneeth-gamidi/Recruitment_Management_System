from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.core.config import Settings, get_settings
from src.models import RefreshToken, User
from src.services.access_token_service import AuthenticatedUserContext

RAW_TOKEN_BYTES = 32
RAW_TOKEN_FORMAT = re.compile(r"^[A-Za-z0-9_-]{43}$")
INVALID_REFRESH_TOKEN_MESSAGE = "Invalid authentication credentials."


class InvalidRefreshToken(ValueError):
    """Public-safe failure for invalid, expired, revoked, or replayed tokens."""


class RefreshTokenServiceUsageError(RuntimeError):
    """Raised when a caller attempts to use a service-owned session transaction."""


@dataclass(frozen=True)
class RefreshTokenGrant:
    raw_token: str
    token_id: UUID
    family_id: UUID
    expires_at: datetime
    family_expires_at: datetime


@dataclass(frozen=True)
class RefreshTokenRotation:
    grant: RefreshTokenGrant
    user_id: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _new_raw_token() -> str:
    return secrets.token_urlsafe(RAW_TOKEN_BYTES)


def _digest_token(raw_token: str) -> bytes:
    return hashlib.sha256(raw_token.encode("ascii")).digest()


def _validate_raw_token(raw_token: str) -> bytes:
    if not isinstance(raw_token, str) or not RAW_TOKEN_FORMAT.fullmatch(raw_token):
        raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)
    return _digest_token(raw_token)


def _require_service_owned_transaction(session: Session) -> None:
    if session.in_transaction():
        raise RefreshTokenServiceUsageError(
            "Refresh-token services require a session without an active transaction."
        )


def _active_user_for_update(session: Session, user_id: str) -> User:
    user = session.scalar(
        select(User)
        .where(User.user_id == user_id, User.status == "ACTIVE")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)
    return user


def _grant_from_row(raw_token: str, row: RefreshToken) -> RefreshTokenGrant:
    return RefreshTokenGrant(
        raw_token=raw_token,
        token_id=row.token_id,
        family_id=row.family_id,
        expires_at=_as_utc(row.expires_at),
        family_expires_at=_as_utc(row.family_expires_at),
    )


def create_refresh_token_family(
    session: Session,
    user: User,
    *,
    settings: Settings | None = None,
) -> RefreshTokenGrant:
    """Create one refresh-token family and commit it before exposing its secret.

    The service owns the supplied session's transaction. The caller must pass a
    session with no active transaction and a persisted User; only the current
    database account state is trusted.
    """
    _require_service_owned_transaction(session)
    if not isinstance(user, User) or not user.user_id:
        raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)

    app_settings = settings or get_settings()
    now = _utcnow()
    family_expires_at = now + timedelta(
        days=app_settings.refresh_token_family_lifetime_days
    )
    expires_at = min(
        now + timedelta(days=app_settings.refresh_token_lifetime_days),
        family_expires_at,
    )
    raw_token = _new_raw_token()
    row = RefreshToken(
        token_id=uuid4(),
        user_id=user.user_id,
        token_digest=_digest_token(raw_token),
        family_id=uuid4(),
        issued_at=now,
        family_expires_at=family_expires_at,
        expires_at=expires_at,
    )

    with session.begin():
        active_user = _active_user_for_update(session, user.user_id)
        row.user_id = active_user.user_id
        session.add(row)
        session.flush()

    return _grant_from_row(raw_token, row)


def rotate_refresh_token(
    session: Session,
    raw_token: str,
    *,
    settings: Settings | None = None,
) -> RefreshTokenRotation:
    """Rotate a token atomically; replay revocation is committed before failure.

    The service owns the session transaction and commits a successful
    replacement before returning its secret. It locks the owner row first,
    then all token rows in that family in stable order. A consumed token is
    treated as replay: all family rows are revoked and committed, then the
    caller receives the same generic failure as any other invalid token.
    """
    _require_service_owned_transaction(session)
    digest = _validate_raw_token(raw_token)
    app_settings = settings or get_settings()
    result: RefreshTokenRotation | None = None
    replay_detected = False

    try:
        with session.begin():
            hint = session.scalar(
                select(RefreshToken).where(RefreshToken.token_digest == digest)
            )
            if hint is None or not hmac.compare_digest(hint.token_digest, digest):
                raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)

            active_user = _active_user_for_update(session, hint.user_id)
            family_rows = list(
                session.scalars(
                    select(RefreshToken)
                    .where(RefreshToken.family_id == hint.family_id)
                    .order_by(RefreshToken.token_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                ).all()
            )
            current = next(
                (row for row in family_rows if row.token_id == hint.token_id),
                None,
            )
            if (
                current is None
                or current.user_id != active_user.user_id
                or not hmac.compare_digest(current.token_digest, digest)
            ):
                raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)

            if current.replaced_by_token_id is not None:
                session.execute(
                    update(RefreshToken)
                    .where(RefreshToken.family_id == current.family_id)
                    .values(
                        revoked_at=func.coalesce(
                            RefreshToken.revoked_at,
                            _utcnow(),
                        )
                    )
                    .execution_options(synchronize_session=False)
                )
                replay_detected = True
            elif current.revoked_at is not None:
                raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)
            else:
                now = _utcnow()
                family_expiries = {
                    _as_utc(row.family_expires_at)
                    for row in family_rows
                }
                if (
                    len(family_expiries) != 1
                    or any(row.user_id != active_user.user_id for row in family_rows)
                ):
                    session.execute(
                        update(RefreshToken)
                        .where(RefreshToken.family_id == current.family_id)
                        .values(revoked_at=_coalesce_revocation(now))
                        .execution_options(synchronize_session=False)
                    )
                    replay_detected = True
                else:
                    family_expires_at = family_expiries.pop()
                    family_is_active = any(row.revoked_at is None for row in family_rows)
                    if (
                        not family_is_active
                        or _as_utc(current.expires_at) <= now
                        or family_expires_at <= now
                    ):
                        raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)

                    replacement_raw = _new_raw_token()
                    replacement_id = uuid4()
                    replacement_expires_at = min(
                        now + timedelta(days=app_settings.refresh_token_lifetime_days),
                        family_expires_at,
                    )
                    if replacement_expires_at <= now:
                        raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)

                    replacement = RefreshToken(
                        token_id=replacement_id,
                        user_id=active_user.user_id,
                        token_digest=_digest_token(replacement_raw),
                        family_id=current.family_id,
                        issued_at=now,
                        family_expires_at=family_expires_at,
                        expires_at=replacement_expires_at,
                    )
                    session.add(replacement)
                    session.flush()
                    current.last_used_at = now
                    current.revoked_at = now
                    current.replaced_by_token_id = replacement_id
                    session.flush()
                    result = RefreshTokenRotation(
                        grant=_grant_from_row(replacement_raw, replacement),
                        user_id=active_user.user_id,
                    )
    except InvalidRefreshToken:
        raise

    if replay_detected:
        raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)
    if result is None:
        raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)
    return result


def revoke_refresh_token_family(
    session: Session,
    authenticated_user: AuthenticatedUserContext,
    family_id: UUID,
) -> int:
    """Revoke one owned family idempotently; ownership comes from auth context."""
    _require_service_owned_transaction(session)
    if not isinstance(authenticated_user, AuthenticatedUserContext):
        raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)
    now = _utcnow()
    revoked_count = 0
    with session.begin():
        _lock_user(session, authenticated_user.user_id)
        family_rows = list(
            session.scalars(
                select(RefreshToken)
                .where(RefreshToken.family_id == family_id)
                .order_by(RefreshToken.token_id)
                .with_for_update()
            ).all()
        )
        if not family_rows or any(
            row.user_id != authenticated_user.user_id for row in family_rows
        ):
            raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)
        for row in family_rows:
            if row.revoked_at is None:
                row.revoked_at = now
                revoked_count += 1
        session.flush()
    return revoked_count


def revoke_all_user_refresh_tokens(session: Session, user_id: str) -> int:
    """Revoke every active refresh token for an existing user.

    This service does not increment token_version; access-token invalidation is
    a separate operation owned by account/password lifecycle services.
    """
    _require_service_owned_transaction(session)
    now = _utcnow()
    revoked_count = 0
    with session.begin():
        _lock_user(session, user_id)
        rows = list(
            session.scalars(
                select(RefreshToken)
                .where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .order_by(RefreshToken.token_id)
                .with_for_update()
            ).all()
        )
        for row in rows:
            row.revoked_at = now
            revoked_count += 1
        session.flush()
    return revoked_count


def _lock_user(session: Session, user_id: str) -> User:
    user = session.scalar(
        select(User)
        .where(User.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise InvalidRefreshToken(INVALID_REFRESH_TOKEN_MESSAGE)
    return user


def _coalesce_revocation(now: datetime):
    return func.coalesce(RefreshToken.revoked_at, now)
