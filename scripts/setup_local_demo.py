from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database.base import Base
from src.models import AuditEvent, Role, User, UserRole
from src.rbac.seed import seed_rbac
from src.services.account_service import normalize_email
from src.services.password_security import hash_password, validate_password


def create_local_demo_database(
    database_path: Path,
    *,
    email: str,
    display_name: str,
    password: str,
    recruiter_department: str,
) -> str:
    email = normalize_email(email)
    display_name = display_name.strip()
    recruiter_department = recruiter_department.strip()
    if not display_name or len(display_name) > 200:
        raise ValueError("Display name must contain 1 to 200 non-whitespace characters.")
    if not recruiter_department or len(recruiter_department) > 100:
        raise ValueError("Recruiter department must contain 1 to 100 non-whitespace characters.")
    validate_password(password)
    password_hash = hash_password(password)
    del password

    database_path = database_path.expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = database_path.with_name(database_path.name + ".setup")
    if database_path.exists() or temporary_path.exists():
        raise FileExistsError(
            "The local demo database already exists. Refusing to overwrite it."
        )

    temporary_path.touch(exist_ok=False)
    engine = create_engine(
        URL.create("sqlite", database=temporary_path.as_posix()),
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    user_id = f"USR-{uuid4()}"
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session, session.begin():
            seed_rbac(session)
            now = datetime.now(timezone.utc)
            user = User(
                user_id=user_id,
                email=email,
                display_name=display_name,
                password_hash=password_hash,
                status="ACTIVE",
                email_verified_at=now,
                password_changed_at=now,
            )
            session.add(user)
            session.flush()

            for role_code, scope_type, department in (
                ("ADMIN", "GLOBAL", None),
                ("RECRUITER", "DEPARTMENT", recruiter_department),
                ("APPROVER", "RESOURCE", None),
            ):
                role = session.scalar(
                    select(Role).where(
                        Role.role_code == role_code,
                        Role.is_system.is_(True),
                        Role.is_active.is_(True),
                    )
                )
                if role is None:
                    raise RuntimeError(f"Required built-in role {role_code!r} is missing.")
                session.add(
                    UserRole(
                        user_id=user_id,
                        role_id=role.role_id,
                        scope_type=scope_type,
                        scope_department=department,
                        assigned_by_user_id=user_id,
                    )
                )
            session.add(
                AuditEvent(
                    audit_event_id=f"AUDIT-{uuid4().hex}",
                    event_type="INITIAL_DEMO_ADMIN_BOOTSTRAPPED",
                    entity_type="USER",
                    entity_id=user_id,
                    new_state="ACTIVE",
                    actor_type="SYSTEM",
                    reason="Explicitly requested local demo administrator setup.",
                )
            )

        engine.dispose()
        temporary_path.replace(database_path)
        return user_id
    finally:
        engine.dispose()
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create an isolated SQLite demo database and an explicitly requested "
            "administrator account."
        )
    )
    parser.add_argument("--email", required=True, help="Administrator sign-in email")
    parser.add_argument("--name", required=True, help="Administrator display name")
    parser.add_argument(
        "--recruiter-department",
        default="Engineering",
        help="Department in which this account can perform recruiter actions (default: Engineering).",
    )
    args = parser.parse_args()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable; choose a protected user-only directory.")
    database_path = (
        Path(local_app_data) / "RecruitmentManagementSystem" / "demo.sqlite3"
    )

    print(
        "Password entry is hidden: type your password normally and press Enter; "
        "no characters or dots will appear.",
        flush=True,
    )
    password = getpass.getpass("Choose administrator password (12+ characters): ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if password != confirmation:
        parser.error("Passwords do not match.")

    user_id = create_local_demo_database(
        database_path,
        email=args.email,
        display_name=args.name,
        password=password,
        recruiter_department=args.recruiter_department,
    )
    database_url = URL.create("sqlite", database=database_path.as_posix()).render_as_string(
        hide_password=False
    )
    print(f"Created local demo administrator {user_id} ({normalize_email(args.email)}).")
    print(f"Database target: {database_path}")
    print("Use these commands in this PowerShell window to start the application:")
    print(f"$env:DATABASE_URL = '{database_url}'")
    print("$env:JWT_ISSUER = 'http://127.0.0.1:8000'")
    print("$env:JWT_AUDIENCE = 'recruitment-local'")
    print(
        "$env:JWT_PRIVATE_KEY_PATH = Join-Path $env:LOCALAPPDATA "
        "'RecruitmentManagementSystem\\keys\\jwt-private.pem'"
    )
    print(
        "$env:JWT_PUBLIC_KEY_PATH = Join-Path $env:LOCALAPPDATA "
        "'RecruitmentManagementSystem\\keys\\jwt-public.pem'"
    )
    print(".\\.venv312\\Scripts\\python.exe main.py")
    print("Sign in at http://127.0.0.1:8000/ui/ using the email and password you chose.")


if __name__ == "__main__":
    main()
