from __future__ import annotations

from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.core.config import Settings
from src.database.base import Base
from src.database.session import get_db
from src.models import Role, User, UserRole
from src.rbac.seed import seed_rbac
from src.services.password_security import hash_password


@pytest.fixture
def engine():
    from sqlalchemy import create_engine

    database_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(database_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def auth_context(tmp_path, engine):
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
    with Session(engine) as session, session.begin():
        seed_rbac(session)
        admin_role = session.scalar(select(Role).where(Role.role_code == "ADMIN"))
        user = User(
            user_id="USR-AUTH-1",
            email="admin@example.invalid",
            display_name="Test Admin",
            password_hash=hash_password("test password with sufficient length"),
            status="ACTIVE",
            email_verified_at=datetime.now(timezone.utc),
            password_changed_at=datetime.now(timezone.utc),
        )
        session.add(user)
        session.flush()
        assert admin_role is not None
        session.add(
            UserRole(
                user_id=user.user_id,
                role_id=admin_role.role_id,
                scope_type="GLOBAL",
            )
        )
    return settings


@pytest.fixture
def client(engine, auth_context):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with session_factory() as session:
            yield session

    app = create_app(auth_context)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


def login(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.invalid",
            "password": "test password with sufficient length",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_login_returns_access_token_and_httponly_refresh_cookie(client) -> None:
    result = login(client)
    assert result["token_type"] == "Bearer"
    assert result["expires_in"] == 600
    assert result["access_token"]
    assert result["csrf_token"]
    cookie = client.cookies.get("rms_refresh")
    assert cookie and cookie not in result.values()

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {result['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["user_id"] == "USR-AUTH-1"
    assert me.json()["roles"] == ["ADMIN"]


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("unknown@example.invalid", "test password with sufficient length"),
        ("admin@example.invalid", "wrong password"),
    ],
)
def test_login_failure_is_generic(client, email: str, password: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password."}


def test_fifth_failed_password_temporarily_locks_account(client, engine) -> None:
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.invalid", "password": "incorrect password"},
        )
        assert response.status_code == 401
    with Session(engine) as session:
        user = session.get(User, "USR-AUTH-1")
        assert user is not None
        assert user.status == "LOCKED"
        assert user.locked_until is not None


def test_refresh_rotates_cookie_and_logout_revokes_family(client, engine) -> None:
    credentials = login(client)
    previous_refresh = client.cookies.get("rms_refresh")
    csrf_token = credentials["csrf_token"]
    headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf_token,
    }

    refreshed = client.post("/api/v1/auth/refresh", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != credentials["access_token"]
    replacement = client.cookies.get("rms_refresh")
    assert replacement and replacement != previous_refresh

    logout = client.post(
        "/api/v1/auth/logout",
        headers={
            **headers,
            "Authorization": f"Bearer {refreshed.json()['access_token']}",
        },
    )
    assert logout.status_code == 204
    assert client.cookies.get("rms_refresh") is None

    with Session(engine) as session:
        from src.models import RefreshToken

        rows = list(session.scalars(select(RefreshToken)))
        assert len(rows) == 2
        assert all(row.revoked_at is not None for row in rows)


def test_refresh_requires_csrf_origin_and_logout_requires_auth(client) -> None:
    login(client)
    invalid = client.post(
        "/api/v1/auth/refresh",
        headers={"Origin": "http://attacker.example.invalid", "X-CSRF-Token": "bad"},
    )
    assert invalid.status_code == 403
    assert client.post("/api/v1/auth/logout").status_code == 401
