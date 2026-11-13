from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url

from src.database.base import Base
from src.models import auth as auth_models  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
BASE_REVISION = "f7aa32690f38"
AUTH_REVISION = "c1a8b04d5e29"
AUTH_TEST_ENV = "AUTH_RBAC_TEST_DATABASE_URL"
AUTH_TABLES = {
    "users",
    "roles",
    "permissions",
    "user_roles",
    "role_permissions",
    "refresh_tokens",
    "account_action_tokens",
}
EXPECTED_ROLE_PERMISSIONS = {
    "ADMIN": {
        "users.manage", "roles.manage", "permissions.read", "configuration.manage",
        "requisitions.read", "candidates.read", "applications.read", "interviews.read",
        "scorecards.read", "offers.read", "audit.read",
    },
    "RECRUITER": {
        "requisitions.read", "requisitions.create", "requisitions.update",
        "candidates.read", "candidates.create", "candidates.update",
        "applications.read", "applications.manage", "applications.transition",
        "interviews.read", "interviews.schedule", "interviews.reschedule",
        "scorecards.read", "offers.read", "offers.create",
    },
    "HIRING_MANAGER": {
        "requisitions.read", "candidates.read", "applications.read",
        "hiring.recommend", "interviews.read", "scorecards.read", "offers.read",
    },
    "INTERVIEWER": {
        "candidates.read", "applications.read", "interviews.read",
        "scorecards.submit", "scorecards.read",
    },
    "APPROVER": {
        "requisitions.read", "requisitions.approve", "candidates.read",
        "applications.read", "scorecards.read", "offers.read", "offers.approve",
        "compensation_exceptions.approve", "audit.read",
    },
}


def _migration(database_url: str, action: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment.pop("AUTH_RBAC_TEST_DATABASE_URL", None)
    command = [sys.executable, "-m", "alembic", action]
    if revision:
        command.append(revision)
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        redacted = database_url
        try:
            redacted = make_url(database_url).render_as_string(hide_password=True)
        except Exception:
            pass
        output = f"{result.stdout}\n{result.stderr}".replace(database_url, "<redacted test URL>")
        output = output.replace(redacted, "<redacted test URL>")
        pytest.fail(f"Alembic {action} {revision} failed:\n{output}")


def _table_snapshot(connection, table_names: set[str]) -> dict[str, tuple]:
    inspector = inspect(connection)
    snapshot = {}
    for table_name in sorted(table_names):
        columns = tuple(
            sorted(
                (
                    column["name"],
                    str(column["type"]),
                    column["nullable"],
                    str(column["default"]),
                )
                for column in inspector.get_columns(table_name)
            )
        )
        primary_key = tuple(sorted(inspector.get_pk_constraint(table_name)["constrained_columns"] or []))
        foreign_keys = tuple(
            sorted(
                (
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                    tuple(foreign_key["referred_columns"]),
                    foreign_key.get("options", {}).get("ondelete"),
                )
                for foreign_key in inspector.get_foreign_keys(table_name)
            )
        )
        unique_constraints = tuple(
            sorted(
                tuple(constraint["column_names"] or [])
                for constraint in inspector.get_unique_constraints(table_name)
            )
        )
        checks = tuple(
            sorted(check["sqltext"] for check in inspector.get_check_constraints(table_name))
        )
        indexes = tuple(
            sorted(
                (
                    index["name"],
                    tuple(index["column_names"] or []),
                    index["unique"],
                    str(index.get("dialect_options", {})),
                )
                for index in inspector.get_indexes(table_name)
            )
        )
        snapshot[table_name] = (
            columns,
            primary_key,
            foreign_keys,
            unique_constraints,
            checks,
            indexes,
        )
    return snapshot


@pytest.mark.skipif(
    not os.environ.get(AUTH_TEST_ENV),
    reason=f"Requires a separately provisioned PostgreSQL test DB in {AUTH_TEST_ENV}.",
)
def test_postgresql_migration_upgrade_constraints_and_safe_downgrade() -> None:
    database_url = os.environ[AUTH_TEST_ENV]
    test_url = make_url(database_url)

    from src.config import DATABASE_URL

    configured_url = make_url(DATABASE_URL)
    assert test_url.get_backend_name() == "postgresql"
    assert test_url.database and test_url.database.startswith("recruitment_auth_rbac_test")
    assert (test_url.host, test_url.port, test_url.database) != (
        configured_url.host,
        configured_url.port,
        configured_url.database,
    ), "Refusing to migrate: auth test DB must differ from the configured database."
    print(
        "PostgreSQL test target (credentials redacted): "
        f"host={test_url.host}, port={test_url.port}, database={test_url.database}; "
        f"configured database={configured_url.database}"
    )

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            identity = connection.execute(
                text("SELECT current_database(), inet_server_addr()::text, inet_server_port()")
            ).one()
            assert identity[0] == test_url.database
            table_names = set(inspect(connection).get_table_names())
        recruitment_tables = set(Base.metadata.tables) - AUTH_TABLES
        expected_base_tables = recruitment_tables | {"alembic_version"}
        assert len(recruitment_tables) == 21
        assert table_names in (set(), expected_base_tables, expected_base_tables | AUTH_TABLES)

        if table_names == set():
            _migration(database_url, "upgrade", BASE_REVISION)
        elif table_names == expected_base_tables | AUTH_TABLES:
            _migration(database_url, "downgrade", BASE_REVISION)

        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == expected_base_tables
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == BASE_REVISION
            before = _table_snapshot(connection, recruitment_tables)

        _migration(database_url, "upgrade", AUTH_REVISION)
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert set(inspector.get_table_names()) == expected_base_tables | AUTH_TABLES
            after = _table_snapshot(connection, recruitment_tables)
            assert after == before

            assert set(inspector.get_pk_constraint("role_permissions")["constrained_columns"]) == {
                "role_id", "permission_id"
            }
            assert inspector.get_foreign_keys("users")
            assert inspector.get_check_constraints("users")
            assert inspector.get_check_constraints("user_roles")
            assert inspector.get_check_constraints("refresh_tokens")
            assert inspector.get_check_constraints("account_action_tokens")
            grant_index = next(
                index for index in inspector.get_indexes("user_roles")
                if index["name"] == "uq_user_roles_active_scope"
            )
            assert grant_index["unique"] is True
            token_columns = {
                column["name"] for column in inspector.get_columns("refresh_tokens")
            }
            assert "family_expires_at" in token_columns
            assert "user_id" in token_columns

            role_mapping = {
                role_code: set()
                for role_code in EXPECTED_ROLE_PERMISSIONS
            }
            rows = connection.execute(
                text(
                    "SELECT r.role_code, p.permission_code "
                    "FROM role_permissions rp "
                    "JOIN roles r USING (role_id) "
                    "JOIN permissions p USING (permission_id)"
                )
            ).all()
            for role_code, permission_code in rows:
                role_mapping[role_code].add(permission_code)
            assert role_mapping == EXPECTED_ROLE_PERMISSIONS
            assert len(connection.execute(text("SELECT role_id FROM roles")).all()) == 5
            assert len(connection.execute(text("SELECT permission_id FROM permissions")).all()) == 25
            assert connection.scalar(text("SELECT count(*) FROM users")) == 0
            permission_rows = dict(
                connection.execute(
                    text("SELECT permission_code, description FROM permissions")
                ).all()
            )
            from src.rbac.seed import PERMISSION_DEFINITIONS

            assert permission_rows == {
                definition.code: definition.description
                for definition in PERMISSION_DEFINITIONS
            }

        _verify_postgresql_specific_constraints(engine)
        _migration(database_url, "check", "")
        _migration(database_url, "downgrade", BASE_REVISION)
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == expected_base_tables
            assert _table_snapshot(connection, recruitment_tables) == before
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == BASE_REVISION
    finally:
        engine.dispose()


def _verify_postgresql_specific_constraints(engine) -> None:
    from hashlib import sha256

    now = "2026-01-01T00:00:00+00:00"
    user_id = f"USR-TEST-{uuid4()}"
    family_id = uuid4()
    invalid_token_id = uuid4()
    digest = sha256(uuid4().bytes).digest()

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (user_id, email, display_name) "
                "VALUES (:user_id, :email, 'Temporary migration test only')"
            ),
            {"user_id": user_id, "email": f"{user_id.lower()}@example.invalid"},
        )
        role_id = connection.scalar(text("SELECT role_id FROM roles WHERE role_code='RECRUITER'"))
        connection.execute(
            text(
                "INSERT INTO user_roles "
                "(user_role_id, user_id, role_id, scope_type) "
                "VALUES (:grant_id, :user_id, :role_id, 'GLOBAL')"
            ),
            {"grant_id": uuid4(), "user_id": user_id, "role_id": role_id},
        )
        nested = connection.begin_nested()
        try:
            connection.execute(
                text(
                    "INSERT INTO user_roles "
                    "(user_role_id, user_id, role_id, scope_type) "
                    "VALUES (:grant_id, :user_id, :role_id, 'GLOBAL')"
                ),
                {"grant_id": uuid4(), "user_id": user_id, "role_id": role_id},
            )
        except IntegrityError:
            nested.rollback()
        else:
            nested.rollback()
            pytest.fail("PostgreSQL allowed a duplicate active GLOBAL grant with NULL scope columns.")

        nested = connection.begin_nested()
        try:
            connection.execute(
                text(
                    "INSERT INTO refresh_tokens "
                    "(token_id, user_id, token_digest, family_id, issued_at, "
                    "family_expires_at, expires_at) "
                    "VALUES (:token_id, :user_id, :digest, :family_id, :issued, :family_expiry, :expiry)"
                ),
                {
                    "token_id": invalid_token_id,
                    "user_id": user_id,
                    "digest": digest,
                    "family_id": family_id,
                    "issued": now,
                    "family_expiry": "2026-01-20T00:00:00+00:00",
                    "expiry": "2026-01-21T00:00:00+00:00",
                },
            )
        except IntegrityError:
            nested.rollback()
        else:
            nested.rollback()
            pytest.fail("PostgreSQL allowed token expiry later than family_expires_at.")
        connection.execute(text("DELETE FROM user_roles WHERE user_id = :user_id"), {"user_id": user_id})
        connection.execute(text("DELETE FROM users WHERE user_id = :user_id"), {"user_id": user_id})
