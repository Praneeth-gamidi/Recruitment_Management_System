from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

TIMESTAMP = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_ACTIVATION', 'ACTIVE', 'LOCKED', 'DISABLED')",
            name="status",
        ),
        CheckConstraint("email = lower(email)", name="email_normalized"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_nonnegative"),
        CheckConstraint("token_version > 0", name="token_version_positive"),
        CheckConstraint(
            "(status = 'PENDING_ACTIVATION' AND password_hash IS NULL) OR "
            "(status <> 'PENDING_ACTIVATION' AND password_hash IS NOT NULL)",
            name="password_status",
        ),
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
        Index("ix_users_status", "status"),
    )

    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="PENDING_ACTIVATION"
    )
    hiring_manager_id: Mapped[str | None] = mapped_column(
        String(80),
        ForeignKey("hiring_managers.hiring_manager_id", ondelete="RESTRICT"),
        unique=True,
    )
    interviewer_id: Mapped[str | None] = mapped_column(
        String(80),
        ForeignKey("interviewers.interviewer_id", ondelete="RESTRICT"),
        unique=True,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    password_changed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    hiring_manager = relationship("HiringManager")
    interviewer = relationship("Interviewer")
    role_grants: Mapped[list[UserRole]] = relationship(
        back_populates="user", foreign_keys="UserRole.user_id"
    )
    assigned_role_grants: Mapped[list[UserRole]] = relationship(
        back_populates="assigned_by", foreign_keys="UserRole.assigned_by_user_id"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user")
    account_action_tokens: Mapped[list[AccountActionToken]] = relationship(
        back_populates="user"
    )


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint("role_code = upper(role_code)", name="role_code_normalized"),
        Index("ix_roles_is_active", "is_active"),
    )

    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    role_code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user_grants: Mapped[list[UserRole]] = relationship(back_populates="role")
    permission_grants: Mapped[list[RolePermission]] = relationship(
        back_populates="role"
    )


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = (Index("ix_permissions_is_active", "is_active"),)

    permission_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    permission_code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )

    role_grants: Mapped[list[RolePermission]] = relationship(
        back_populates="permission"
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('GLOBAL', 'DEPARTMENT', 'REQUISITION', 'RESOURCE')",
            name="scope_type",
        ),
        CheckConstraint(
            "(scope_type IN ('GLOBAL', 'RESOURCE') AND "
            "scope_department IS NULL AND scope_requisition_id IS NULL) OR "
            "(scope_type = 'DEPARTMENT' AND scope_department IS NOT NULL AND "
            "scope_requisition_id IS NULL) OR "
            "(scope_type = 'REQUISITION' AND scope_department IS NULL AND "
            "scope_requisition_id IS NOT NULL)",
            name="scope_shape",
        ),
        Index(
            "uq_user_roles_active_scope",
            "user_id",
            "role_id",
            "scope_type",
            "scope_department",
            "scope_requisition_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_user_roles_user_revoked", "user_id", "revoked_at"),
        Index("ix_user_roles_role_revoked", "role_id", "revoked_at"),
        Index("ix_user_roles_scope_department", "scope_department"),
        Index("ix_user_roles_scope_requisition", "scope_requisition_id"),
    )

    user_role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("roles.role_id", ondelete="RESTRICT"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_department: Mapped[str | None] = mapped_column(String(100))
    scope_requisition_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("requisitions.requisition_id", ondelete="RESTRICT")
    )
    assigned_by_user_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    assigned_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)

    user: Mapped[User] = relationship(
        back_populates="role_grants", foreign_keys=[user_id]
    )
    role: Mapped[Role] = relationship(back_populates="user_grants")
    assigned_by: Mapped[User | None] = relationship(
        back_populates="assigned_role_grants", foreign_keys=[assigned_by_user_id]
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        Index("ix_role_permissions_permission_id", "permission_id"),
    )

    role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("roles.role_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    permission_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("permissions.permission_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    granted_by_user_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    granted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )

    role: Mapped[Role] = relationship(back_populates="permission_grants")
    permission: Mapped[Permission] = relationship(back_populates="role_grants")
    granted_by: Mapped[User | None] = relationship(foreign_keys=[granted_by_user_id])


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint(
            "issued_at < expires_at AND expires_at <= family_expires_at",
            name="expiry_order",
        ),
        CheckConstraint("length(token_digest) = 32", name="digest_length"),
        Index("uq_refresh_tokens_token_digest", "token_digest", unique=True),
        Index("ix_refresh_tokens_user_expiry", "user_id", "revoked_at", "expires_at"),
        Index("ix_refresh_tokens_family_revoked", "family_id", "revoked_at"),
    )

    token_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    token_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    family_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    family_expires_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    replaced_by_token_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("refresh_tokens.token_id", ondelete="RESTRICT")
    )
    user_agent: Mapped[str | None] = mapped_column(String(500))

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
    replaced_by: Mapped[RefreshToken | None] = relationship(
        remote_side="RefreshToken.token_id", back_populates="replaces"
    )
    replaces: Mapped[RefreshToken | None] = relationship(back_populates="replaced_by")


class AccountActionToken(Base):
    __tablename__ = "account_action_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('ACTIVATION', 'PASSWORD_RESET')", name="purpose"
        ),
        CheckConstraint("issued_at < expires_at", name="expiry_order"),
        CheckConstraint("length(token_digest) = 32", name="digest_length"),
        Index("uq_account_action_tokens_digest", "token_digest", unique=True),
        Index(
            "ix_account_action_tokens_user_purpose_expiry",
            "user_id",
            "purpose",
            "expires_at",
        ),
    )

    token_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    token_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)

    user: Mapped[User] = relationship(back_populates="account_action_tokens")
