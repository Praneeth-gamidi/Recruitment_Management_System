"""Additive authentication and RBAC foundation.

Revision ID: c1a8b04d5e29
Revises: f7aa32690f38
"""
from __future__ import annotations

from typing import Sequence, Union
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1a8b04d5e29"
down_revision: Union[str, Sequence[str], None] = "f7aa32690f38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMESPACE = UUID("60dbe960-3482-46bb-9898-020ad2dd9519")
ROLES = (
    ("ADMIN", "Admin", "Provision/deactivate users, manage role and permission configuration, view system-wide recruitment data and audit events."),
    ("RECRUITER", "Recruiter", "Create/manage requisitions, candidates, and applications; make permitted stage changes; schedule/reschedule interviews; initiate offers."),
    ("HIRING_MANAGER", "Hiring Manager", "Review assigned requisitions and candidates, record hiring recommendations, and view submitted interview feedback."),
    ("INTERVIEWER", "Interviewer", "View assigned interviews and minimum candidate context; submit and view own scorecards."),
    ("APPROVER", "Approver", "Decide assigned requisition/offer approvals and compensation exceptions."),
)
PERMISSIONS = (
    ("users.manage", "Provision, list, read, and update user accounts and status.", ("ADMIN",)),
    ("roles.manage", "Create/manage role definitions and assign/revoke role grants.", ("ADMIN",)),
    ("permissions.read", "Read the canonical permission catalog.", ("ADMIN",)),
    ("configuration.manage", "Manage system configuration.", ("ADMIN",)),
    ("requisitions.read", "Read requisition fields needed by the user's assigned work.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "APPROVER")),
    ("requisitions.create", "Create a requisition.", ("RECRUITER",)),
    ("requisitions.update", "Edit permitted requisition fields.", ("RECRUITER",)),
    ("requisitions.approve", "Decide an assigned requisition approval.", ("APPROVER",)),
    ("hiring.recommend", "Record a Hiring Manager's candidate/hiring recommendation.", ("HIRING_MANAGER",)),
    ("candidates.read", "Read candidate details required for assigned recruitment work.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER", "APPROVER")),
    ("candidates.create", "Create a candidate profile.", ("RECRUITER",)),
    ("candidates.update", "Update candidate profile fields.", ("RECRUITER",)),
    ("applications.read", "Read applications and status needed for authorized work.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER", "APPROVER")),
    ("applications.manage", "Manage application records other than stage transitions.", ("RECRUITER",)),
    ("applications.transition", "Move an application through permitted stages.", ("RECRUITER",)),
    ("interviews.read", "Read interview details and schedules.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER")),
    ("interviews.schedule", "Schedule an interview.", ("RECRUITER",)),
    ("interviews.reschedule", "Reschedule an interview.", ("RECRUITER",)),
    ("scorecards.submit", "Create/submit a review scorecard.", ("INTERVIEWER",)),
    ("scorecards.read", "Read scorecards and review feedback.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER", "APPROVER")),
    ("offers.read", "Read offer terms and status required for authorized work.", ("ADMIN", "RECRUITER", "HIRING_MANAGER", "APPROVER")),
    ("offers.create", "Initiate a new offer version.", ("RECRUITER",)),
    ("offers.approve", "Decide an assigned standard offer approval.", ("APPROVER",)),
    ("compensation_exceptions.approve", "Decide an assigned compensation exception approval.", ("APPROVER",)),
    ("audit.read", "Read audit events.", ("ADMIN", "APPROVER")),
)


def _id(kind: str, code: str) -> UUID:
    return uuid5(NAMESPACE, f"{kind}:{code}")


def _seed_catalog(connection: sa.Connection) -> None:
    role_table = sa.table(
        "roles",
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
        sa.column("role_code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_system", sa.Boolean),
        sa.column("is_active", sa.Boolean),
    )
    permission_table = sa.table(
        "permissions",
        sa.column("permission_id", postgresql.UUID(as_uuid=True)),
        sa.column("permission_code", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_active", sa.Boolean),
    )
    role_permission_table = sa.table(
        "role_permissions",
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
        sa.column("permission_id", postgresql.UUID(as_uuid=True)),
    )

    role_rows = [
        {
            "role_id": _id("role", code),
            "role_code": code,
            "name": name,
            "description": description,
            "is_system": True,
            "is_active": True,
        }
        for code, name, description in ROLES
    ]
    permission_rows = [
        {
            "permission_id": _id("permission", code),
            "permission_code": code,
            "description": description,
            "is_active": True,
        }
        for code, description, _ in PERMISSIONS
    ]
    connection.execute(
        postgresql.insert(role_table).values(role_rows).on_conflict_do_nothing()
    )
    connection.execute(
        postgresql.insert(permission_table)
        .values(permission_rows)
        .on_conflict_do_nothing()
    )

    roles_by_code = dict(
        connection.execute(
            sa.select(role_table.c.role_code, role_table.c.role_id)
        ).all()
    )
    permissions_by_code = dict(
        connection.execute(
            sa.select(permission_table.c.permission_code, permission_table.c.permission_id)
        ).all()
    )
    expected_roles = {
        row["role_code"]: (
            row["name"],
            row["description"],
            row["is_system"],
            row["is_active"],
        )
        for row in role_rows
    }
    actual_roles = {
        code: (name, description, is_system, is_active)
        for code, name, description, is_system, is_active in connection.execute(
            sa.select(
                role_table.c.role_code,
                role_table.c.name,
                role_table.c.description,
                role_table.c.is_system,
                role_table.c.is_active,
            ).where(role_table.c.role_code.in_(expected_roles))
        )
    }
    if actual_roles != expected_roles:
        raise RuntimeError("Existing built-in role records differ from the migration seed.")
    if any(roles_by_code[code] != _id("role", code) for code in expected_roles):
        raise RuntimeError("Existing built-in role identifiers differ from the deterministic migration seed.")
    expected_permissions = {
        row["permission_code"]: (row["description"], row["is_active"])
        for row in permission_rows
    }
    actual_permissions = {
        code: (description, is_active)
        for code, description, is_active in connection.execute(
            sa.select(
                permission_table.c.permission_code,
                permission_table.c.description,
                permission_table.c.is_active,
            ).where(permission_table.c.permission_code.in_(expected_permissions))
        )
    }
    if actual_permissions != expected_permissions:
        raise RuntimeError("Existing canonical permission records differ from the migration seed.")
    if any(permissions_by_code[code] != _id("permission", code) for code in expected_permissions):
        raise RuntimeError("Existing permission identifiers differ from the deterministic migration seed.")

    expected_grants = {
        (roles_by_code[role_code], permissions_by_code[permission_code])
        for permission_code, _, role_codes in PERMISSIONS
        for role_code in role_codes
    }
    current_grants = set(
        connection.execute(
            sa.select(role_permission_table.c.role_id, role_permission_table.c.permission_id)
        ).all()
    )
    if not current_grants.issubset(expected_grants):
        raise RuntimeError("Existing built-in role-permission grants differ from the migration seed.")
    missing = expected_grants - current_grants
    if missing:
        connection.execute(
            postgresql.insert(role_permission_table).values(
                [{"role_id": role_id, "permission_id": permission_id} for role_id, permission_id in missing]
            ).on_conflict_do_nothing()
        )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(80), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), server_default="PENDING_ACTIVATION", nullable=False),
        sa.Column("hiring_manager_id", sa.String(80), nullable=True),
        sa.Column("interviewer_id", sa.String(80), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING_ACTIVATION', 'ACTIVE', 'LOCKED', 'DISABLED')",
            name=op.f("ck_users_status"),
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_normalized")),
        sa.CheckConstraint("failed_login_count >= 0", name=op.f("ck_users_failed_login_count_nonnegative")),
        sa.CheckConstraint("token_version > 0", name=op.f("ck_users_token_version_positive")),
        sa.CheckConstraint(
            "(status = 'PENDING_ACTIVATION' AND password_hash IS NULL) OR "
            "(status <> 'PENDING_ACTIVATION' AND password_hash IS NOT NULL)",
            name=op.f("ck_users_password_status"),
        ),
        sa.ForeignKeyConstraint(
            ["hiring_manager_id"], ["hiring_managers.hiring_manager_id"],
            name=op.f("fk_users_hiring_manager_id_hiring_managers"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["interviewer_id"], ["interviewers.interviewer_id"],
            name=op.f("fk_users_interviewer_id_interviewers"), ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("hiring_manager_id", name=op.f("uq_users_hiring_manager_id")),
        sa.UniqueConstraint("interviewer_id", name=op.f("uq_users_interviewer_id")),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_index("ix_users_status", "users", ["status"], unique=False)

    op.create_table(
        "roles",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role_code = upper(role_code)", name=op.f("ck_roles_role_code_normalized")),
        sa.PrimaryKeyConstraint("role_id", name=op.f("pk_roles")),
        sa.UniqueConstraint("role_code", name=op.f("uq_roles_role_code")),
    )
    op.create_index("ix_roles_is_active", "roles", ["is_active"], unique=False)

    op.create_table(
        "permissions",
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_code", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("permission_id", name=op.f("pk_permissions")),
        sa.UniqueConstraint("permission_code", name=op.f("uq_permissions_permission_code")),
    )
    op.create_index("ix_permissions_is_active", "permissions", ["is_active"], unique=False)

    op.create_table(
        "user_roles",
        sa.Column("user_role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(80), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_department", sa.String(100), nullable=True),
        sa.Column("scope_requisition_id", sa.String(80), nullable=True),
        sa.Column("assigned_by_user_id", sa.String(80), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('GLOBAL', 'DEPARTMENT', 'REQUISITION', 'RESOURCE')",
            name=op.f("ck_user_roles_scope_type"),
        ),
        sa.CheckConstraint(
            "(scope_type IN ('GLOBAL', 'RESOURCE') AND scope_department IS NULL AND scope_requisition_id IS NULL) OR "
            "(scope_type = 'DEPARTMENT' AND scope_department IS NOT NULL AND scope_requisition_id IS NULL) OR "
            "(scope_type = 'REQUISITION' AND scope_department IS NULL AND scope_requisition_id IS NOT NULL)",
            name=op.f("ck_user_roles_scope_shape"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name=op.f("fk_user_roles_user_id_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.role_id"], name=op.f("fk_user_roles_role_id_roles"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scope_requisition_id"], ["requisitions.requisition_id"], name=op.f("fk_user_roles_scope_requisition_id_requisitions"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.user_id"], name=op.f("fk_user_roles_assigned_by_user_id_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_role_id", name=op.f("pk_user_roles")),
    )
    op.create_index(
        "uq_user_roles_active_scope",
        "user_roles",
        ["user_id", "role_id", "scope_type", "scope_department", "scope_requisition_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_user_roles_user_revoked", "user_roles", ["user_id", "revoked_at"], unique=False)
    op.create_index("ix_user_roles_role_revoked", "user_roles", ["role_id", "revoked_at"], unique=False)
    op.create_index("ix_user_roles_scope_department", "user_roles", ["scope_department"], unique=False)
    op.create_index("ix_user_roles_scope_requisition", "user_roles", ["scope_requisition_id"], unique=False)

    op.create_table(
        "role_permissions",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_by_user_id", sa.String(80), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.role_id"], name=op.f("fk_role_permissions_role_id_roles"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.permission_id"], name=op.f("fk_role_permissions_permission_id_permissions"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.user_id"], name=op.f("fk_role_permissions_granted_by_user_id_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name=op.f("pk_role_permissions")),
    )
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"], unique=False)

    op.create_table(
        "refresh_tokens",
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(80), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("family_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.CheckConstraint("issued_at < expires_at AND expires_at <= family_expires_at", name=op.f("ck_refresh_tokens_expiry_order")),
        sa.CheckConstraint("length(token_digest) = 32", name=op.f("ck_refresh_tokens_digest_length")),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name=op.f("fk_refresh_tokens_user_id_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replaced_by_token_id"], ["refresh_tokens.token_id"], name=op.f("fk_refresh_tokens_replaced_by_token_id_refresh_tokens"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("token_id", name=op.f("pk_refresh_tokens")),
    )
    op.create_index("uq_refresh_tokens_token_digest", "refresh_tokens", ["token_digest"], unique=True)
    op.create_index("ix_refresh_tokens_user_expiry", "refresh_tokens", ["user_id", "revoked_at", "expires_at"], unique=False)
    op.create_index("ix_refresh_tokens_family_revoked", "refresh_tokens", ["family_id", "revoked_at"], unique=False)

    op.create_table(
        "account_action_tokens",
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(80), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('ACTIVATION', 'PASSWORD_RESET')", name=op.f("ck_account_action_tokens_purpose")),
        sa.CheckConstraint("issued_at < expires_at", name=op.f("ck_account_action_tokens_expiry_order")),
        sa.CheckConstraint("length(token_digest) = 32", name=op.f("ck_account_action_tokens_digest_length")),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name=op.f("fk_account_action_tokens_user_id_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("token_id", name=op.f("pk_account_action_tokens")),
    )
    op.create_index("uq_account_action_tokens_digest", "account_action_tokens", ["token_digest"], unique=True)
    op.create_index(
        "ix_account_action_tokens_user_purpose_expiry",
        "account_action_tokens",
        ["user_id", "purpose", "expires_at"],
        unique=False,
    )
    _seed_catalog(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    for table in (
        "users",
        "user_roles",
        "refresh_tokens",
        "account_action_tokens",
    ):
        count = connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"'))
        if count:
            raise RuntimeError(
                f"Refusing to drop {table}: it contains records; preserve authentication data before downgrade."
            )

    expected_role_codes = {code for code, _, _ in ROLES}
    expected_permission_codes = {code for code, _, _ in PERMISSIONS}
    expected_roles = {
        code: (name, description, True, True)
        for code, name, description in ROLES
    }
    actual_roles = {
        code: (name, description, is_system, is_active)
        for code, name, description, is_system, is_active in connection.execute(
            sa.text("SELECT role_code, name, description, is_system, is_active FROM roles")
        )
    }
    expected_permissions = {
        code: (description, True)
        for code, description, _ in PERMISSIONS
    }
    actual_permissions = {
        code: (description, is_active)
        for code, description, is_active in connection.execute(
            sa.text("SELECT permission_code, description, is_active FROM permissions")
        )
    }
    if actual_roles != expected_roles or actual_permissions != expected_permissions:
        raise RuntimeError("Refusing to drop customized or additional role/permission definitions.")

    role_ids = {code: _id("role", code) for code in expected_role_codes}
    permission_ids = {code: _id("permission", code) for code in expected_permission_codes}
    expected_grants = {
        (role_ids[role_code], permission_ids[permission_code])
        for permission_code, _, role_codes in PERMISSIONS
        for role_code in role_codes
    }
    actual_grants = set(
        connection.execute(
            sa.text("SELECT role_id, permission_id FROM role_permissions")
        ).all()
    )
    if actual_grants != expected_grants:
        raise RuntimeError("Refusing to drop modified role-permission mappings.")

    op.drop_table("account_action_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_role_permissions_permission_id", table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_index("ix_user_roles_scope_requisition", table_name="user_roles")
    op.drop_index("ix_user_roles_scope_department", table_name="user_roles")
    op.drop_index("ix_user_roles_role_revoked", table_name="user_roles")
    op.drop_index("ix_user_roles_user_revoked", table_name="user_roles")
    op.drop_index("uq_user_roles_active_scope", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index("ix_permissions_is_active", table_name="permissions")
    op.drop_table("permissions")
    op.drop_index("ix_roles_is_active", table_name="roles")
    op.drop_table("roles")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
