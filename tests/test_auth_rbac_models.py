from __future__ import annotations

from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex
from sqlalchemy.orm import Session

from src.database.base import Base
from src.models import (
    AccountActionToken,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserRole,
)
from src.rbac.seed import (
    PERMISSION_DEFINITIONS,
    ROLE_DEFINITIONS,
    seed_rbac,
)

AUTH_TABLES = {
    "users",
    "roles",
    "permissions",
    "user_roles",
    "role_permissions",
    "refresh_tokens",
    "account_action_tokens",
}
EXPECTED_ROLE_CODES = {"ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER", "APPROVER"}
EXPECTED_PERMISSION_CODES = {
    "users.manage",
    "roles.manage",
    "permissions.read",
    "configuration.manage",
    "requisitions.read",
    "requisitions.create",
    "requisitions.update",
    "requisitions.approve",
    "hiring.recommend",
    "candidates.read",
    "candidates.create",
    "candidates.update",
    "applications.read",
    "applications.manage",
    "applications.transition",
    "interviews.read",
    "interviews.schedule",
    "interviews.reschedule",
    "scorecards.submit",
    "scorecards.read",
    "offers.read",
    "offers.create",
    "offers.approve",
    "compensation_exceptions.approve",
    "audit.read",
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


def test_seven_auth_models_register_with_expected_relationships() -> None:
    assert AUTH_TABLES <= set(Base.metadata.tables)
    assert len(AUTH_TABLES) == 7

    assert {"role_grants", "refresh_tokens", "account_action_tokens"} <= {
        relationship.key for relationship in inspect(User).relationships
    }
    assert {"user_grants", "permission_grants"} <= {
        relationship.key for relationship in inspect(Role).relationships
    }
    assert {"role_grants"} <= {
        relationship.key for relationship in inspect(Permission).relationships
    }
    assert {"replaced_by", "replaces"} <= {
        relationship.key for relationship in inspect(RefreshToken).relationships
    }


def test_auth_table_columns_keys_constraints_and_indexes_are_declared() -> None:
    expected_columns = {
        "users": {
            "user_id", "email", "display_name", "password_hash", "status",
            "hiring_manager_id", "interviewer_id", "email_verified_at",
            "failed_login_count", "locked_until", "last_login_at",
            "password_changed_at", "token_version", "created_at", "updated_at",
        },
        "roles": {
            "role_id", "role_code", "name", "description", "is_system",
            "is_active", "created_at", "updated_at",
        },
        "permissions": {
            "permission_id", "permission_code", "description", "is_active", "created_at",
        },
        "user_roles": {
            "user_role_id", "user_id", "role_id", "scope_type", "scope_department",
            "scope_requisition_id", "assigned_by_user_id", "assigned_at", "revoked_at",
        },
        "role_permissions": {"role_id", "permission_id", "granted_by_user_id", "granted_at"},
        "refresh_tokens": {
            "token_id", "user_id", "token_digest", "family_id", "issued_at",
            "family_expires_at", "expires_at", "last_used_at", "revoked_at",
            "replaced_by_token_id", "user_agent",
        },
        "account_action_tokens": {
            "token_id", "user_id", "token_digest", "purpose", "issued_at",
            "expires_at", "consumed_at",
        },
    }

    for table_name, columns in expected_columns.items():
        table = Base.metadata.tables[table_name]
        assert set(table.columns.keys()) == columns
        assert len(table.primary_key.columns) >= 1
        assert all(not column.nullable for column in table.primary_key.columns)
        assert table.foreign_keys or table_name in {"roles", "permissions"}

    assert Base.metadata.tables["users"].c.hiring_manager_id.foreign_keys
    assert Base.metadata.tables["users"].c.interviewer_id.foreign_keys
    assert Base.metadata.tables["user_roles"].c.scope_requisition_id.foreign_keys
    assert Base.metadata.tables["role_permissions"].primary_key.columns.keys() == [
        "role_id", "permission_id"
    ]
    assert "family_expires_at" in Base.metadata.tables["refresh_tokens"].c
    assert any(index.name == "uq_user_roles_active_scope" for index in Base.metadata.tables["user_roles"].indexes)
    assert any(index.name == "uq_users_email_lower" for index in Base.metadata.tables["users"].indexes)

    grant_index = next(
        index for index in Base.metadata.tables["user_roles"].indexes
        if index.name == "uq_user_roles_active_scope"
    )
    compiled = str(CreateIndex(grant_index).compile(dialect=postgresql.dialect()))
    assert "NULLS NOT DISTINCT" in compiled
    assert "scope_type" in compiled
    assert "revoked_at IS NULL" in compiled


def test_canonical_role_and_permission_definitions_match_approved_mapping() -> None:
    assert len(ROLE_DEFINITIONS) == 5
    assert {role.code for role in ROLE_DEFINITIONS} == EXPECTED_ROLE_CODES
    assert len(PERMISSION_DEFINITIONS) == 25
    assert {permission.code for permission in PERMISSION_DEFINITIONS} == EXPECTED_PERMISSION_CODES

    actual = {
        role.code: {
            permission.code
            for permission in PERMISSION_DEFINITIONS
            if role.code in permission.roles
        }
        for role in ROLE_DEFINITIONS
    }
    assert actual == EXPECTED_ROLE_PERMISSIONS
    assert "requisitions.read" not in actual["INTERVIEWER"]
    assert not any(
        permission.code.endswith(".approve")
        or permission.code == "compensation_exceptions.approve"
        for permission in PERMISSION_DEFINITIONS
        if "ADMIN" in permission.roles
    )


def test_seed_is_idempotent_and_does_not_create_users_or_change_customized_rows() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            seed_rbac(session)
        with Session(engine) as session, session.begin():
            seed_rbac(session)
            assert len(session.scalars(select(Role)).all()) == 5
            assert len(session.scalars(select(Permission)).all()) == 25
            assert len(session.scalars(select(RolePermission)).all()) == sum(
                len(permissions) for permissions in EXPECTED_ROLE_PERMISSIONS.values()
            )
            assert session.scalar(select(func.count()).select_from(User)) == 0

        with Session(engine) as session, session.begin():
            role = session.scalar(select(Role).where(Role.role_code == "ADMIN"))
            assert role is not None
            role.name = "Locally customized"
        with Session(engine) as session:
            customized_role = session.scalar(select(Role).where(Role.role_code == "ADMIN"))
            assert customized_role is not None
            assert customized_role.name == "Locally customized"
            try:
                seed_rbac(session)
            except ValueError:
                session.rollback()
            else:
                raise AssertionError("Seed must reject modified built-in records without overwriting them.")

        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(User)) == 0
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
