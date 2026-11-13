from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from src.database.base import Base
from src.models import (
    AuditEvent,
    HiringManager,
    Interviewer,
    Role,
    User,
    UserRole,
)
from src.rbac.seed import seed_rbac
from src.services.account_service import (
    ACCOUNT_UNAVAILABLE_MESSAGE,
    AccountAuthorizationError,
    AccountConflictError,
    AccountProvisioningError,
    AccountUnavailableError,
    RoleGrantRequest,
    normalize_email,
    provision_user,
    require_active_account,
)


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


def _add_admin(session: Session) -> User:
    seed_rbac(session)
    admin = User(
        user_id="USR-ADMIN",
        email="admin@example.invalid",
        display_name="Provisioning Admin",
        password_hash="$argon2id$test-hash",
        status="ACTIVE",
    )
    admin_role = session.scalar(select(Role).where(Role.role_code == "ADMIN"))
    assert admin_role is not None
    session.add(admin)
    session.flush()
    session.add(
        UserRole(
            user=admin,
            role=admin_role,
            scope_type="GLOBAL",
        )
    )
    session.flush()
    return admin


def test_normalize_email_uses_trimmed_lowercase_form() -> None:
    assert normalize_email("  Alice.Example@Example.COM ") == "alice.example@example.com"


@pytest.mark.parametrize(
    "email",
    ["", "not-an-email", "@example.invalid", "user@", "a..b@example.invalid", "a b@example.invalid"],
)
def test_invalid_email_is_rejected(email: str) -> None:
    with pytest.raises(AccountProvisioningError):
        normalize_email(email)


@pytest.mark.parametrize("status", ["PENDING_ACTIVATION", "LOCKED", "DISABLED"])
def test_non_active_accounts_are_rejected_with_one_generic_error(engine, status: str) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            User(
                user_id=f"USR-{status}",
                email=f"{status.lower()}@example.invalid",
                display_name=status,
                password_hash=None if status == "PENDING_ACTIVATION" else "$argon2id$test-hash",
                status=status,
            )
        )

    with Session(engine) as session:
        with pytest.raises(AccountUnavailableError) as error:
            require_active_account(session, f"USR-{status}")
        assert str(error.value) == ACCOUNT_UNAVAILABLE_MESSAGE


def test_active_account_passes_and_missing_account_is_generic(engine) -> None:
    with Session(engine) as session, session.begin():
        active = User(
            user_id="USR-ACTIVE",
            email="active@example.invalid",
            display_name="Active User",
            password_hash="$argon2id$test-hash",
            status="ACTIVE",
        )
        session.add(active)

    with Session(engine) as session:
        assert require_active_account(session, "USR-ACTIVE").status == "ACTIVE"
        with pytest.raises(AccountUnavailableError) as error:
            require_active_account(session, "USR-MISSING")
        assert str(error.value) == ACCOUNT_UNAVAILABLE_MESSAGE


def test_provisioning_is_pending_audited_and_does_not_assign_roles_implicitly(engine) -> None:
    with Session(engine) as session, session.begin():
        actor = _add_admin(session)
        manager = HiringManager(
            hiring_manager_id="HM-PROVISION",
            employee_code="hm-provision",
            name="Hiring Manager",
            email="hm@example.invalid",
            department="Engineering",
        )
        interviewer = Interviewer(
            interviewer_id="INT-PROVISION",
            employee_code="int-provision",
            name="Interviewer",
            email="interviewer@example.invalid",
            department="Engineering",
            designation="Engineer",
        )
        session.add_all([manager, interviewer])
        session.flush()
        profile_before = (manager.name, manager.email, manager.department, interviewer.name)

        user = provision_user(
            session,
            actor_user_id=actor.user_id,
            email="  Staff.Member@Example.COM ",
            display_name="  Staff Member  ",
            hiring_manager_id=manager.hiring_manager_id,
            interviewer_id=interviewer.interviewer_id,
        )
        session.flush()

        assert user.email == "staff.member@example.com"
        assert user.display_name == "Staff Member"
        assert user.status == "PENDING_ACTIVATION"
        assert user.password_hash is None
        assert user.role_grants == []
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.entity_id == user.user_id)
        )
        assert audit is not None
        assert audit.event_type == "USER_PROVISIONED"
        assert audit.actor_id == actor.user_id
        assert audit.new_state == "PENDING_ACTIVATION"
        assert (
            manager.name,
            manager.email,
            manager.department,
            interviewer.name,
        ) == profile_before


def test_explicit_approved_role_grants_require_admin_and_valid_scope(engine) -> None:
    with Session(engine) as session, session.begin():
        actor = _add_admin(session)
        user = provision_user(
            session,
            actor_user_id=actor.user_id,
            email="recruiter@example.invalid",
            display_name="Recruiter",
            role_grants=(
                RoleGrantRequest(
                    "RECRUITER",
                    "DEPARTMENT",
                    scope_department=" Engineering ",
                ),
            ),
        )
        grants = list(user.role_grants)
        assert len(grants) == 1
        assert grants[0].role.role_code == "RECRUITER"
        assert grants[0].scope_type == "DEPARTMENT"
        assert grants[0].scope_department == "Engineering"
        assert grants[0].assigned_by_user_id == actor.user_id


def test_unapproved_or_incompatible_role_grants_are_rejected(engine) -> None:
    with Session(engine) as session, session.begin():
        actor = _add_admin(session)
        with pytest.raises(AccountProvisioningError):
            provision_user(
                session,
                actor_user_id=actor.user_id,
                email="unsupported@example.invalid",
                display_name="Unsupported",
                role_grants=(RoleGrantRequest("SUPERUSER", "GLOBAL"),),
            )
        with pytest.raises(AccountProvisioningError):
            provision_user(
                session,
                actor_user_id=actor.user_id,
                email="bad-scope@example.invalid",
                display_name="Bad Scope",
                role_grants=(RoleGrantRequest("INTERVIEWER", "GLOBAL"),),
            )
        assert session.scalar(
            select(User.user_id).where(User.email.in_(
                ["unsupported@example.invalid", "bad-scope@example.invalid"]
            ))
        ) is None


def test_non_admin_cannot_assign_privileged_role(engine) -> None:
    with Session(engine) as session, session.begin():
        seed_rbac(session)
        user = User(
            user_id="USR-RECRUITER-ACTOR",
            email="recruiter.actor@example.invalid",
            display_name="Recruiter Actor",
            password_hash="$argon2id$test-hash",
            status="ACTIVE",
        )
        session.add(user)
        with pytest.raises(AccountAuthorizationError):
            provision_user(
                session,
                actor_user_id=user.user_id,
                email="new-admin@example.invalid",
                display_name="New Admin",
                role_grants=(RoleGrantRequest("ADMIN", "GLOBAL"),),
            )
        assert session.scalar(
            select(User.user_id).where(User.email == "new-admin@example.invalid")
        ) is None


def test_duplicate_email_is_generic_and_creates_no_partial_account(engine) -> None:
    with Session(engine) as session, session.begin():
        actor = _add_admin(session)
        provision_user(
            session,
            actor_user_id=actor.user_id,
            email="duplicate@example.invalid",
            display_name="Original",
        )

    with Session(engine) as session, session.begin():
        actor = session.get(User, "USR-ADMIN")
        assert actor is not None
        with pytest.raises(AccountConflictError) as error:
            provision_user(
                session,
                actor_user_id=actor.user_id,
                email=" DUPLICATE@EXAMPLE.INVALID ",
                display_name="Duplicate",
            )
        assert str(error.value) == "Account could not be provisioned."
        assert session.scalar(
            select(User.user_id).where(User.email == "duplicate@example.invalid")
        ) is not None
        assert session.scalar(
            select(AuditEvent.audit_event_id).where(
                AuditEvent.entity_type == "USER",
                AuditEvent.new_state == "PENDING_ACTIVATION",
            )
        ) is not None
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "USER_PROVISIONED")
        ) == 1


def test_duplicate_profile_link_is_rejected_without_changing_profile(engine) -> None:
    with Session(engine) as session, session.begin():
        actor = _add_admin(session)
        manager = HiringManager(
            hiring_manager_id="HM-LINKED",
            employee_code="hm-linked",
            name="Linked Manager",
            email="linked.manager@example.invalid",
            department="Engineering",
        )
        session.add(manager)
        session.flush()
        provision_user(
            session,
            actor_user_id=actor.user_id,
            email="first.manager.account@example.invalid",
            display_name="First Account",
            hiring_manager_id=manager.hiring_manager_id,
        )
        profile_before = (manager.name, manager.email, manager.department)

        with pytest.raises(AccountConflictError) as error:
            provision_user(
                session,
                actor_user_id=actor.user_id,
                email="second.manager.account@example.invalid",
                display_name="Second Account",
                hiring_manager_id=manager.hiring_manager_id,
            )
        assert str(error.value) == "Account could not be provisioned."
        assert (
            manager.name,
            manager.email,
            manager.department,
        ) == profile_before
        assert session.scalar(
            select(User.user_id).where(
                User.email == "second.manager.account@example.invalid"
            )
        ) is None


def test_failed_audit_insert_rolls_back_all_provisioning_records(engine) -> None:
    with Session(engine) as session, session.begin():
        actor = _add_admin(session)
        session.execute(
            text(
                "CREATE TRIGGER reject_user_provisioning_audit "
                "BEFORE INSERT ON audit_events "
                "WHEN NEW.event_type = 'USER_PROVISIONED' "
                "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
            )
        )
        with pytest.raises(AccountConflictError):
            provision_user(
                session,
                actor_user_id=actor.user_id,
                email="rolled-back@example.invalid",
                display_name="Must Roll Back",
                role_grants=(
                    RoleGrantRequest(
                        "RECRUITER",
                        "DEPARTMENT",
                        scope_department="Engineering",
                    ),
                ),
            )
        assert session.scalar(
            select(User.user_id).where(User.email == "rolled-back@example.invalid")
        ) is None
        assert session.scalar(
            select(UserRole.user_role_id)
            .join(User, User.user_id == UserRole.user_id)
            .where(
                User.email == "rolled-back@example.invalid"
            )
        ) is None
        assert session.scalar(
            select(AuditEvent.audit_event_id).where(
                AuditEvent.event_type == "USER_PROVISIONED"
            )
        ) is None
