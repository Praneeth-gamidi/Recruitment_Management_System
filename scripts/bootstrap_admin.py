from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import DATABASE_URL
from src.database.connection import get_engine
from src.models import AuditEvent, Role, RolePermission, User, UserRole
from src.services.account_service import normalize_email
from src.services.password_security import hash_password, validate_password


def _database_identity(engine) -> tuple[str, str]:
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            database, host, port = connection.execute(
                text("SELECT current_database(), inet_server_addr()::text, inet_server_port()")
            ).one()
        return host or "local socket", database
    return engine.url.host or "local", engine.url.database or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the first active administrator on an explicitly confirmed database."
    )
    parser.add_argument("--email", required=True, help="Administrator work email")
    parser.add_argument("--name", required=True, help="Administrator display name")
    parser.add_argument(
        "--recruiter-department",
        help="Optionally grant RECRUITER access scoped to this department.",
    )
    parser.add_argument(
        "--approver",
        action="store_true",
        help="Explicitly grant APPROVER role in addition to ADMIN.",
    )
    args = parser.parse_args()

    email = normalize_email(args.email)
    name = args.name.strip()
    if not name or len(name) > 200:
        parser.error("--name must contain 1 to 200 non-whitespace characters.")
    if args.recruiter_department is not None:
        args.recruiter_department = args.recruiter_department.strip()
        if not args.recruiter_department or len(args.recruiter_department) > 100:
            parser.error("--recruiter-department must contain 1 to 100 characters.")

    first_password = getpass.getpass("Choose administrator password (12+ characters): ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if first_password != confirmation:
        parser.error("Passwords do not match.")
    validate_password(first_password)
    password_hash = hash_password(first_password)
    del first_password, confirmation

    engine = get_engine(url=DATABASE_URL)
    try:
        host, database = _database_identity(engine)
        url = make_url(str(DATABASE_URL))
        if database == "recruitment_db":
            raise RuntimeError(
                "Refusing to bootstrap on recruitment_db. Configure and confirm an isolated target."
            )
        print(f"Target: host={host}, port={url.port or 'default'}, database={database}")
        if input("Type the database name exactly to continue: ").strip() != database:
            raise RuntimeError("Database confirmation did not match; no account was created.")

        with Session(engine, expire_on_commit=False) as session, session.begin():
            required_tables = {"users", "roles", "permissions", "role_permissions", "user_roles"}
            existing_tables = set(inspect(engine).get_table_names())
            if not required_tables.issubset(existing_tables):
                raise RuntimeError("Authentication schema is missing; apply the approved migration first.")
            if session.scalar(
                select(User.user_id)
                .join(UserRole, UserRole.user_id == User.user_id)
                .join(Role, Role.role_id == UserRole.role_id)
                .where(
                    Role.role_code == "ADMIN",
                    User.status == "ACTIVE",
                    UserRole.revoked_at.is_(None),
                )
                .limit(1)
            ):
                raise RuntimeError("An active administrator already exists; refusing bootstrap.")

            admin_role = session.scalar(
                select(Role).where(
                    Role.role_code == "ADMIN",
                    Role.is_system.is_(True),
                    Role.is_active.is_(True),
                )
            )
            if admin_role is None or session.scalar(
                select(RolePermission.role_id)
                .where(RolePermission.role_id == admin_role.role_id)
                .limit(1)
            ) is None:
                raise RuntimeError("Built-in RBAC seed data is missing; run the approved seed migration.")

            user = User(
                user_id=f"USR-{uuid4()}",
                email=email,
                display_name=name,
                password_hash=password_hash,
                status="ACTIVE",
                email_verified_at=datetime.now(timezone.utc),
                password_changed_at=datetime.now(timezone.utc),
            )
            session.add(user)
            session.flush()
            roles_to_assign = [("ADMIN", "GLOBAL", None)]
            if args.recruiter_department:
                roles_to_assign.append(("RECRUITER", "DEPARTMENT", args.recruiter_department))
            if args.approver:
                roles_to_assign.append(("APPROVER", "RESOURCE", None))
            for role_code, scope_type, department in roles_to_assign:
                role = session.scalar(
                    select(Role).where(
                        Role.role_code == role_code,
                        Role.is_system.is_(True),
                        Role.is_active.is_(True),
                    )
                )
                if role is None:
                    raise RuntimeError(f"Built-in {role_code} role is missing.")
                session.add(
                    UserRole(
                        user_id=user.user_id,
                        role_id=role.role_id,
                        scope_type=scope_type,
                        scope_department=department,
                        assigned_by_user_id=user.user_id,
                    )
                )
            session.add(
                AuditEvent(
                    audit_event_id=f"AUDIT-{uuid4().hex}",
                    event_type="INITIAL_ADMIN_BOOTSTRAPPED",
                    entity_type="USER",
                    entity_id=user.user_id,
                    new_state="ACTIVE",
                    actor_type="SYSTEM",
                    reason="One-time, explicitly confirmed administrator bootstrap.",
                )
            )
            session.flush()
            print(f"Created administrator account {user.user_id} for {user.email}.")
            print(f"Explicit role grants: {', '.join(role[0] for role in roles_to_assign)}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
