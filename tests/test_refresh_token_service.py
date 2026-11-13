from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import Settings
from src.database.base import Base
from src.models import RefreshToken, User
from src.services.access_token_service import AuthenticatedUserContext
from src.services.refresh_token_service import (
    INVALID_REFRESH_TOKEN_MESSAGE,
    InvalidRefreshToken,
    RefreshTokenGrant,
    RefreshTokenServiceUsageError,
    create_refresh_token_family,
    revoke_all_user_refresh_tokens,
    revoke_refresh_token_family,
    rotate_refresh_token,
)

AUTH_TEST_ENV = "AUTH_RBAC_TEST_DATABASE_URL"
USER_ID = "USR-REFRESH-TEST"


@pytest.fixture
def engine():
    database_engine = create_engine("sqlite://")

    @event.listens_for(database_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


def _insert_user(engine, *, status: str = "ACTIVE", token_version: int = 1) -> User:
    user = User(
        user_id=USER_ID,
        email="refresh.test@example.invalid",
        display_name="Refresh Test",
        status=status,
        password_hash=None if status == "PENDING_ACTIVATION" else "$argon2id$test",
        token_version=token_version,
    )
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(user)
    return user


def _settings(
    *,
    token_lifetime_days: int = 7,
    family_lifetime_days: int = 30,
) -> Settings:
    return Settings.from_env(
        {
            "REFRESH_TOKEN_LIFETIME_DAYS": str(token_lifetime_days),
            "REFRESH_TOKEN_FAMILY_LIFETIME_DAYS": str(family_lifetime_days),
        }
    )


def _rows(engine, family_id):
    with Session(engine) as session:
        return list(
            session.scalars(
                select(RefreshToken)
                .where(RefreshToken.family_id == family_id)
                .order_by(RefreshToken.issued_at, RefreshToken.token_id)
            ).all()
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_token_generation_is_urlsafe_random_and_only_digest_is_stored(engine) -> None:
    user = _insert_user(engine)
    with Session(engine) as session:
        first = create_refresh_token_family(session, user)
    with Session(engine) as session:
        second = create_refresh_token_family(session, user)

    assert first.raw_token != second.raw_token
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first.raw_token)
    assert len(first.raw_token.encode("ascii")) >= 43
    assert first.raw_token.encode("ascii") not in [
        row.token_digest for row in _rows(engine, first.family_id)
    ]
    assert all(len(row.token_digest) == 32 for row in _rows(engine, first.family_id))


def test_family_creation_uses_configured_lifetimes_and_active_user(engine, monkeypatch) -> None:
    from src.services import refresh_token_service

    user = _insert_user(engine)
    now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(refresh_token_service, "_utcnow", lambda: now)
    settings = _settings(token_lifetime_days=5, family_lifetime_days=12)

    with Session(engine) as session:
        grant = create_refresh_token_family(session, user, settings=settings)

    assert grant.expires_at == now + timedelta(days=5)
    assert grant.family_expires_at == now + timedelta(days=12)
    rows = _rows(engine, grant.family_id)
    assert len(rows) == 1
    assert rows[0].user_id == user.user_id
    assert rows[0].token_digest != grant.raw_token.encode("ascii")
    assert rows[0].expires_at <= rows[0].family_expires_at


@pytest.mark.parametrize("status", ["PENDING_ACTIVATION", "LOCKED", "DISABLED"])
def test_inactive_accounts_cannot_create_or_rotate_tokens(engine, status: str) -> None:
    user = _insert_user(engine, status=status)
    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken) as error:
            create_refresh_token_family(session, user)
    assert str(error.value) == INVALID_REFRESH_TOKEN_MESSAGE
    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken):
            rotate_refresh_token(session, "A" * 43)


def test_rotation_preserves_family_expiry_and_only_one_replacement_exists(engine) -> None:
    user = _insert_user(engine)
    with Session(engine) as session:
        original = create_refresh_token_family(session, user)
    with Session(engine) as session:
        rotated = rotate_refresh_token(session, original.raw_token)

    assert rotated.user_id == user.user_id
    assert rotated.grant.raw_token != original.raw_token
    assert rotated.grant.family_id == original.family_id
    assert rotated.grant.family_expires_at == original.family_expires_at
    rows = _rows(engine, original.family_id)
    assert len(rows) == 2
    assert {_utc(row.family_expires_at) for row in rows} == {
        original.family_expires_at
    }
    assert all(row.expires_at <= row.family_expires_at for row in rows)
    old_row = next(row for row in rows if row.token_id == original.token_id)
    assert old_row.revoked_at is not None
    assert old_row.last_used_at is not None
    assert old_row.replaced_by_token_id == rotated.grant.token_id
    assert sum(row.revoked_at is None for row in rows) == 1


def test_rotation_bounds_replacement_expiry_to_remaining_family_lifetime(
    engine,
    monkeypatch,
) -> None:
    from src.services import refresh_token_service

    user = _insert_user(engine)
    now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(refresh_token_service, "_utcnow", lambda: now)
    settings = _settings(token_lifetime_days=7, family_lifetime_days=30)
    with Session(engine) as session:
        original = create_refresh_token_family(session, user, settings=settings)
    with Session(engine) as session, session.begin():
        row = session.get(RefreshToken, original.token_id)
        assert row is not None
        row.expires_at = original.family_expires_at

    rotation_time = now + timedelta(days=29, hours=23)
    monkeypatch.setattr(refresh_token_service, "_utcnow", lambda: rotation_time)
    with Session(engine) as session:
        rotated = rotate_refresh_token(
            session,
            original.raw_token,
            settings=settings,
        )

    assert rotated.grant.family_expires_at == original.family_expires_at
    assert _utc(rotated.grant.expires_at) == original.family_expires_at
    assert rotated.grant.expires_at <= rotated.grant.family_expires_at


@pytest.mark.parametrize("expiry_kind", ["token", "family"])
def test_expired_token_or_family_cannot_rotate(engine, monkeypatch, expiry_kind: str) -> None:
    from src.services import refresh_token_service

    user = _insert_user(engine)
    now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(refresh_token_service, "_utcnow", lambda: now)
    settings = (
        _settings(token_lifetime_days=3, family_lifetime_days=4)
        if expiry_kind == "token"
        else _settings(token_lifetime_days=7, family_lifetime_days=7)
    )
    with Session(engine) as session:
        original = create_refresh_token_family(session, user, settings=settings)

    advance = (
        timedelta(days=3, seconds=1)
        if expiry_kind == "token"
        else timedelta(days=8)
    )
    monkeypatch.setattr(
        refresh_token_service,
        "_utcnow",
        lambda: now + advance,
    )
    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken):
            rotate_refresh_token(session, original.raw_token, settings=settings)


def test_active_token_cannot_rotate_after_account_is_disabled(engine) -> None:
    user = _insert_user(engine)
    with Session(engine) as session:
        original = create_refresh_token_family(session, user)
    with Session(engine) as session, session.begin():
        persisted = session.get(User, user.user_id)
        assert persisted is not None
        persisted.status = "DISABLED"
    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken) as error:
            rotate_refresh_token(session, original.raw_token)
    assert str(error.value) == INVALID_REFRESH_TOKEN_MESSAGE


def test_unknown_malformed_and_revoked_tokens_fail_generically(engine) -> None:
    user = _insert_user(engine)
    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken) as malformed:
            rotate_refresh_token(session, "not-a-token")
    assert str(malformed.value) == INVALID_REFRESH_TOKEN_MESSAGE

    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken) as unknown:
            rotate_refresh_token(session, "A" * 43)
    assert str(unknown.value) == INVALID_REFRESH_TOKEN_MESSAGE

    with Session(engine) as session:
        grant = create_refresh_token_family(session, user)
    with Session(engine) as session:
        context = AuthenticatedUserContext(user.user_id, str(uuid4()), 1)
        assert revoke_refresh_token_family(session, context, grant.family_id) == 1
    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken) as revoked:
            rotate_refresh_token(session, grant.raw_token)
    assert str(revoked.value) == INVALID_REFRESH_TOKEN_MESSAGE


def test_replay_revokes_entire_family_and_commits_before_failure(engine) -> None:
    user = _insert_user(engine)
    with Session(engine) as session:
        original = create_refresh_token_family(session, user)
    with Session(engine) as session:
        replacement = rotate_refresh_token(session, original.raw_token)

    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken) as error:
            rotate_refresh_token(session, original.raw_token)
    assert str(error.value) == INVALID_REFRESH_TOKEN_MESSAGE

    rows = _rows(engine, original.family_id)
    assert len(rows) == 2
    assert all(row.revoked_at is not None for row in rows)
    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken):
            rotate_refresh_token(session, replacement.grant.raw_token)


def test_session_revocation_is_owned_idempotent_and_does_not_change_version(engine) -> None:
    user = _insert_user(engine, token_version=5)
    with Session(engine) as session:
        first = create_refresh_token_family(session, user)
    with Session(engine) as session:
        second = create_refresh_token_family(session, user)
    context = AuthenticatedUserContext(user.user_id, str(uuid4()), 5)

    with Session(engine) as session:
        with pytest.raises(InvalidRefreshToken):
            revoke_refresh_token_family(
                session,
                AuthenticatedUserContext("USR-OTHER", str(uuid4()), 1),
                first.family_id,
            )
    with Session(engine) as session:
        assert revoke_refresh_token_family(session, context, first.family_id) == 1
    with Session(engine) as session:
        assert revoke_refresh_token_family(session, context, first.family_id) == 0
    with Session(engine) as session:
        assert revoke_all_user_refresh_tokens(session, user.user_id) == 1

    rows = _rows(engine, first.family_id) + _rows(engine, second.family_id)
    assert len(rows) == 2
    assert all(row.revoked_at is not None for row in rows)
    with Session(engine) as session:
        persisted = session.get(User, user.user_id)
        assert persisted is not None
        assert persisted.token_version == 5


def test_refresh_service_requires_session_owned_transactions(engine) -> None:
    user = _insert_user(engine)
    with Session(engine) as session:
        session.execute(select(User.user_id))
        with pytest.raises(RefreshTokenServiceUsageError):
            create_refresh_token_family(session, user)


def test_postgresql_simultaneous_rotation_serializes_and_detects_replay():
    database_url = os.environ.get(AUTH_TEST_ENV)
    if not database_url:
        pytest.skip(f"Requires isolated PostgreSQL in {AUTH_TEST_ENV}.")

    from src.config import DATABASE_URL

    target_url = make_url(database_url)
    configured_url = make_url(DATABASE_URL)
    assert target_url.get_backend_name() == "postgresql"
    assert target_url.database and target_url.database.startswith(
        "recruitment_auth_rbac_test"
    )
    assert (target_url.host, target_url.port, target_url.database) != (
        configured_url.host,
        configured_url.port,
        configured_url.database,
    ), "Refusing PostgreSQL concurrency test against the configured database."

    admin_engine = create_engine(database_url, pool_pre_ping=True)
    schema = f"auth_refresh_test_{uuid4().hex}"
    schema_engine = None
    schema_created = False
    try:
        with admin_engine.connect() as connection:
            identity = connection.execute(
                text("SELECT current_database(), inet_server_addr()::text, inet_server_port()")
            ).one()
            if identity[0] != target_url.database:
                pytest.fail("PostgreSQL test database identity does not match configured URL.")
            if connection.scalar(
                text("SELECT 1 FROM pg_namespace WHERE nspname = :schema"),
                {"schema": schema},
            ):
                pytest.fail("Generated isolated PostgreSQL schema unexpectedly exists.")
            print(
                "PostgreSQL concurrency target (credentials redacted): "
                f"host={identity[1]}, port={identity[2]}, database={identity[0]}, "
                f"schema={schema}; configured database={configured_url.database}"
            )
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.commit()
            schema_created = True

        schema_engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={schema},public"},
        )
        Base.metadata.create_all(schema_engine)
        factory = sessionmaker(bind=schema_engine, expire_on_commit=False)
        user = User(
            user_id="USR-PG-REFRESH",
            email="pg.refresh@example.invalid",
            display_name="PostgreSQL Refresh",
            status="ACTIVE",
            password_hash="$argon2id$test",
        )
        with factory() as session, session.begin():
            session.add(user)
        with factory() as session:
            grant = create_refresh_token_family(session, user)

        start = threading.Barrier(2)

        def rotate_concurrently() -> RefreshTokenGrant | str:
            with factory() as session:
                start.wait(timeout=10)
                try:
                    return rotate_refresh_token(session, grant.raw_token).grant
                except InvalidRefreshToken:
                    return "invalid"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: rotate_concurrently(), range(2)))

        successes = [outcome for outcome in outcomes if isinstance(outcome, RefreshTokenGrant)]
        failures = [outcome for outcome in outcomes if outcome == "invalid"]
        assert len(successes) == 1
        assert len(failures) == 1
        with factory() as session:
            rows = list(
                session.scalars(
                    select(RefreshToken).where(
                        RefreshToken.family_id == grant.family_id
                    )
                ).all()
            )
            assert len(rows) == 2
            assert all(row.revoked_at is not None for row in rows)
            assert {row.family_expires_at for row in rows} == {
                grant.family_expires_at
            }
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if schema_created:
            with admin_engine.connect() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                connection.commit()
                assert connection.scalar(
                    text("SELECT 1 FROM pg_namespace WHERE nspname = :schema"),
                    {"schema": schema},
                ) is None
        admin_engine.dispose()
