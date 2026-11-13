from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.api.app import create_app
from src.core.config import Settings
from src.database.session import get_db
from src.models import Permission, Role, User, UserRole
from src.rbac.seed import PERMISSION_DEFINITIONS
from src.services.password_security import verify_password
from scripts.setup_local_demo import create_local_demo_database


def test_local_demo_admin_can_sign_in_and_has_explicit_workflow_roles(tmp_path) -> None:
    database_path = tmp_path / "demo.sqlite3"
    user_id = create_local_demo_database(
        database_path,
        email=" Demo.Admin@Example.Invalid ",
        display_name="Demo Administrator",
        password="a secure demo password",
        recruiter_department="Engineering",
    )

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.email == "demo.admin@example.invalid"
        assert user.status == "ACTIVE"
        assert verify_password("a secure demo password", user.password_hash)
        assert session.scalar(select(func.count(Permission.permission_id))) == len(
            PERMISSION_DEFINITIONS
        )
        grants = session.execute(
            select(Role.role_code, UserRole.scope_type, UserRole.scope_department)
            .join(UserRole, UserRole.role_id == Role.role_id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.role_code)
        ).all()
        assert grants == [
            ("ADMIN", "GLOBAL", None),
            ("APPROVER", "RESOURCE", None),
            ("RECRUITER", "DEPARTMENT", "Engineering"),
        ]

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp_path / "jwt-private.pem"
    public_path = tmp_path / "jwt-public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings = Settings(
        "Test API",
        "1.0",
        "test",
        "WARNING",
        (),
        "127.0.0.1",
        8000,
        jwt_issuer="https://test.example.invalid",
        jwt_audience="test-recruitment-api",
        jwt_private_key_path=str(private_path),
        jwt_public_key_path=str(public_path),
    )

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with session_factory() as session:
            yield session

    app = create_app(settings)
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={
                    "email": "demo.admin@example.invalid",
                    "password": "a secure demo password",
                },
            )
            assert response.status_code == 200
            client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
            current_user = client.get("/api/v1/auth/me")
            assert current_user.status_code == 200
            assert current_user.json()["roles"] == ["ADMIN", "APPROVER", "RECRUITER"]
    finally:
        engine.dispose()


def test_local_demo_setup_refuses_to_overwrite_existing_database(tmp_path) -> None:
    database_path = tmp_path / "demo.sqlite3"
    database_path.write_text("preserve existing file", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_local_demo_database(
            database_path,
            email="admin@example.invalid",
            display_name="Demo Administrator",
            password="a secure demo password",
            recruiter_department="Engineering",
        )

    assert database_path.read_text(encoding="utf-8") == "preserve existing file"
