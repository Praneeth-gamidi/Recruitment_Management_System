from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.config import Settings
from src.database.session import get_db


def test_application_initialization_exposes_health_and_recruitment_routes() -> None:
    app = create_app(
        Settings(
            app_name="Test Recruitment API",
            app_version="9.8.7",
            environment="test",
            log_level="WARNING",
            cors_origins=("http://localhost:3000",),
            host="127.0.0.1",
            port=8000,
        )
    )
    paths = {route.path for route in app.routes}

    assert app.title == "Test Recruitment API"
    assert app.version == "9.8.7"
    assert {"/", "/health", "/health/db", "/docs", "/openapi.json"} <= paths
    assert {
        "/api/v1/dashboard",
        "/api/v1/requisitions",
        "/api/v1/candidates",
        "/api/v1/applications",
        "/ui",
    } <= paths


def test_root_endpoint_returns_application_metadata() -> None:
    app = create_app(
        Settings("Test API", "1.2.3", "test", "WARNING", (), "127.0.0.1", 8000)
    )
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "application": "Test API",
        "version": "1.2.3",
        "status": "ok",
    }


def test_health_endpoint() -> None:
    with TestClient(create_app(Settings("Test API", "1.0", "test", "WARNING", (), "127.0.0.1", 8000))) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_database_health_success_uses_existing_session_dependency() -> None:
    class FakeSession:
        executed: Any = None

        def execute(self, statement: Any) -> None:
            self.executed = statement

    fake_session = FakeSession()

    def override_db():
        yield fake_session

    app = create_app(Settings("Test API", "1.0", "test", "WARNING", (), "127.0.0.1", 8000))
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "connected"}
    assert "SELECT 1" in str(fake_session.executed)


def test_database_health_failure_is_sanitized() -> None:
    class FakeSession:
        def execute(self, _statement: Any) -> None:
            raise RuntimeError("secret database password")

    def override_db():
        yield FakeSession()

    app = create_app(Settings("Test API", "1.0", "test", "WARNING", (), "127.0.0.1", 8000))
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "database_unavailable",
            "message": "Database health check failed.",
        }
    }
    assert "secret database password" not in response.text


def test_swagger_docs_are_available() -> None:
    with TestClient(create_app(Settings("Test API", "1.0", "test", "WARNING", (), "127.0.0.1", 8000))) as client:
        response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_recruitment_ui_is_available() -> None:
    with TestClient(create_app(Settings("Test API", "1.0", "test", "WARNING", (), "127.0.0.1", 8000))) as client:
        response = client.get("/ui/")

    assert response.status_code == 200
    assert "TalentDesk" in response.text


def test_unhandled_exception_returns_generic_error() -> None:
    app = create_app(Settings("Test API", "1.0", "test", "WARNING", (), "127.0.0.1", 8000))
    router = APIRouter()

    @router.get("/test/unhandled")
    def raise_error() -> None:
        raise RuntimeError("private diagnostic detail")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test/unhandled")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    assert "private diagnostic detail" not in response.text


def test_request_validation_exception_uses_standard_422_response() -> None:
    app = create_app(Settings("Test API", "1.0", "test", "WARNING", (), "127.0.0.1", 8000))
    router = APIRouter()

    @router.get("/test/validated")
    def validated(value: int) -> dict[str, int]:
        return {"value": value}

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/test/validated", params={"value": "not-an-integer"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "value"]
