from __future__ import annotations

from datetime import date

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from src.api.app import create_app
from src.core.config import Settings
from src.database.base import Base
from src.database.session import get_db
from src.models import (
    ApplicationStageHistory,
    AuditEvent,
    Candidate,
    HiringManager,
    Role,
    Requisition,
    User,
    UserRole,
)
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
def client(engine, tmp_path):
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
    with Session(engine, expire_on_commit=False) as session, session.begin():
        seed_rbac(session)
        user = User(
            user_id="USR-RECRUITMENT-TEST",
            email="recruiter@example.invalid",
            display_name="Recruitment Test",
            password_hash=hash_password("recruitment test password"),
            status="ACTIVE",
        )
        session.add(user)
        session.flush()
        for role_code in ("ADMIN", "RECRUITER"):
            role = session.scalar(select(Role).where(Role.role_code == role_code))
            assert role is not None
            session.add(
                UserRole(
                    user_id=user.user_id,
                    role_id=role.role_id,
                    scope_type="GLOBAL",
                )
            )
        approver_role = session.scalar(
            select(Role).where(Role.role_code == "APPROVER")
        )
        assert approver_role is not None
        approver = User(
            user_id="USR-APPROVER-TEST",
            email="approver@example.invalid",
            display_name="Test Approver",
            password_hash=hash_password("approver test password"),
            status="ACTIVE",
        )
        session.add(approver)
        session.flush()
        session.add(
            UserRole(
                user_id=approver.user_id,
                role_id=approver_role.role_id,
                scope_type="GLOBAL",
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
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        auth_response = test_client.post(
            "/api/v1/auth/login",
            json={
                "email": "recruiter@example.invalid",
                "password": "recruitment test password",
            },
        )
        assert auth_response.status_code == 200
        test_client.headers["Authorization"] = (
            f"Bearer {auth_response.json()['access_token']}"
        )
        yield test_client


def add_manager(engine) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            HiringManager(
                hiring_manager_id="HM-1",
                employee_code="hm-1",
                name="Taylor Manager",
                email="manager@example.invalid",
                department="Engineering",
                active_status="ACTIVE",
            )
        )


def sign_in_as(client, email: str, password: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def manager_payload(**overrides) -> dict:
    return {
        "employee_code": "HM-1",
        "name": "Taylor Manager",
        "email": "manager@example.invalid",
        "department": "Engineering",
        "phone": "+1-555-0100",
        **overrides,
    }


def add_open_requisition(engine) -> None:
    add_manager(engine)
    with Session(engine) as session, session.begin():
        session.add(
            Requisition(
                requisition_id="REQ-OPEN",
                hiring_manager_id="HM-1",
                title="Software Engineer",
                description="Build and maintain software.",
                department="Engineering",
                job_family="Software",
                location="Remote",
                employment_type="FULL_TIME",
                work_mode="REMOTE",
                headcount=1,
                status="OPEN",
                opening_date=date(2026, 1, 1),
            )
        )


def candidate_payload(email: str = "jane@example.invalid") -> dict:
    return {
        "first_name": "Jane",
        "last_name": "Candidate",
        "email": email,
        "location": "Remote",
        "total_experience_months": 72,
        "skills": ["Python", "SQL"],
    }


def test_empty_dashboard_and_lists(client) -> None:
    page = client.get("/ui/")
    assert page.status_code == 200
    assert 'id="approvals"' in page.text
    assert 'id="staff"' in page.text
    careers_page = client.get("/careers")
    assert careers_page.status_code == 200
    assert "Find your next opportunity" in careers_page.text
    assert "public/jobs" in careers_page.text
    application_report = client.get("/api/v1/reports/applications.csv")
    assert application_report.status_code == 200
    assert "candidate_email" in application_report.text
    requisition_report = client.get("/api/v1/reports/requisitions.csv")
    assert requisition_report.status_code == 200
    assert "approval_status" in requisition_report.text
    assert client.get("/api/v1/dashboard").json() == {
        "total_requisitions": 0,
        "open_requisitions": 0,
        "total_candidates": 0,
        "total_applications": 0,
        "applications_by_stage": {
            "APPLIED": 0,
            "SCREENING": 0,
            "ASSESSMENT": 0,
            "TECHNICAL_INTERVIEW": 0,
            "MANAGERIAL_INTERVIEW": 0,
            "HR_INTERVIEW": 0,
            "OFFER": 0,
            "HIRED": 0,
            "REJECTED": 0,
            "WITHDRAWN": 0,
        },
        "recent_applications": [],
        "recent_requisitions": [],
    }
    assert client.get("/api/v1/requisitions").json() == []
    assert client.get("/api/v1/candidates").json() == []
    assert client.get("/api/v1/applications").json() == []
    assert client.get("/api/v1/hiring-managers").json() == []


def test_public_jobs_and_candidate_application(client, engine) -> None:
    add_open_requisition(engine)

    jobs = client.get("/api/v1/public/jobs")
    assert jobs.status_code == 200
    assert [job["requisition_id"] for job in jobs.json()] == ["REQ-OPEN"]
    assert client.get("/api/v1/public/jobs?search=not-a-role").json() == []

    response = client.post(
        "/api/v1/public/applications",
        json={
            "requisition_id": "REQ-OPEN",
            "candidate": candidate_payload("Jane.Public@Example.Invalid"),
            "privacy_consent": True,
        },
    )
    assert response.status_code == 201
    application_id = response.json()["application_id"]
    with Session(engine) as session:
        candidate = session.scalar(
            select(Candidate).where(Candidate.email == "jane.public@example.invalid")
        )
        history = session.scalar(
            select(ApplicationStageHistory).where(
                ApplicationStageHistory.application_id == application_id
            )
        )
        audit_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == application_id,
                AuditEvent.entity_type == "APPLICATION",
            )
        )
        assert candidate is not None
        assert history is not None
        assert history.new_stage == "APPLIED"
        assert audit_event is not None
        assert audit_event.actor_id == "CAREER_PORTAL"

    duplicate = client.post(
        "/api/v1/public/applications",
        json={
            "requisition_id": "REQ-OPEN",
            "candidate": candidate_payload("jane.public@example.invalid"),
            "privacy_consent": True,
        },
    )
    assert duplicate.status_code == 409


def test_public_application_requires_consent_and_open_job(client, engine) -> None:
    add_open_requisition(engine)
    missing_consent = client.post(
        "/api/v1/public/applications",
        json={
            "requisition_id": "REQ-OPEN",
            "candidate": candidate_payload(),
            "privacy_consent": False,
        },
    )
    assert missing_consent.status_code == 422

    with Session(engine) as session, session.begin():
        requisition = session.get(Requisition, "REQ-OPEN")
        assert requisition is not None
        requisition.status = "CLOSED"

    assert client.get("/api/v1/public/jobs").json() == []
    closed_job_application = client.post(
        "/api/v1/public/applications",
        json={
            "requisition_id": "REQ-OPEN",
            "candidate": candidate_payload(),
            "privacy_consent": True,
        },
    )
    assert closed_job_application.status_code == 404


def test_hiring_manager_create_list_detail_and_duplicate(client) -> None:
    response = client.post(
        "/api/v1/hiring-managers",
        json=manager_payload(
            employee_code="  HM-Alpha ",
            name=" Taylor Manager ",
            email=" Manager@Example.Invalid ",
            phone="  ",
        ),
    )
    assert response.status_code == 201
    manager = response.json()
    assert manager["hiring_manager_id"]
    assert manager["employee_code"] == "hm-alpha"
    assert manager["email"] == "manager@example.invalid"
    assert manager["name"] == "Taylor Manager"
    assert manager["phone"] is None
    assert manager["active_status"] == "ACTIVE"

    listed = client.get("/api/v1/hiring-managers")
    assert listed.status_code == 200
    assert [item["hiring_manager_id"] for item in listed.json()] == [
        manager["hiring_manager_id"]
    ]
    assert client.get("/api/v1/hiring-managers?active_only=true").json()[0]["active_status"] == "ACTIVE"
    assert client.get(f"/api/v1/hiring-managers/{manager['hiring_manager_id']}").json() == manager

    duplicate = client.post(
        "/api/v1/hiring-managers",
        json=manager_payload(employee_code="hm-beta"),
    )
    assert duplicate.status_code == 409
    assert client.get("/api/v1/hiring-managers/missing").status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": " "},
        {"employee_code": ""},
        {"email": "not-an-email"},
        {"department": ""},
        {"unknown": "not-supported"},
    ],
)
def test_invalid_hiring_manager_input_is_rejected(client, overrides) -> None:
    response = client.post(
        "/api/v1/hiring-managers",
        json=manager_payload(**overrides),
    )
    assert response.status_code == 422


def test_hiring_manager_duplicate_employee_code_is_rejected(client) -> None:
    assert client.post("/api/v1/hiring-managers", json=manager_payload()).status_code == 201
    duplicate = client.post(
        "/api/v1/hiring-managers",
        json=manager_payload(email="another@example.invalid"),
    )
    assert duplicate.status_code == 409


def test_recruitment_api_rejects_non_loopback_callers(engine) -> None:
    def override_db():
        with Session(engine) as session:
            yield session

    app = create_app(Settings("Test API", "1.0", "test", "WARNING", (), "127.0.0.1", 8000))
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("198.51.100.10", 50000)) as test_client:
        assert test_client.get("/api/v1/dashboard").status_code == 403
        assert test_client.get("/health").status_code == 200


def test_create_and_update_requisition_keeps_it_draft(client, engine) -> None:
    manager = client.post("/api/v1/hiring-managers", json=manager_payload()).json()
    response = client.post(
        "/api/v1/requisitions",
        json={
            "hiring_manager_id": manager["hiring_manager_id"],
            "title": "Backend Engineer",
            "department": "Engineering",
            "job_family": "Software",
            "location": "Remote",
            "employment_type": "FULL_TIME",
            "work_mode": "REMOTE",
            "headcount": 2,
            "min_salary": 100000,
            "max_salary": 150000,
            "currency_code": "usd",
            "compensation_period": "YEAR",
            "opening_date": "2026-01-01",
        },
    )
    assert response.status_code == 201
    requisition = response.json()
    assert requisition["status"] == "DRAFT"
    assert requisition["approval_status"] == "NOT_SUBMITTED"
    assert requisition["currency_code"] == "USD"

    updated = client.put(
        f"/api/v1/requisitions/{requisition['requisition_id']}",
        json={"title": "Senior Backend Engineer", "reason": "Updated role scope."},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Senior Backend Engineer"
    assert updated.json()["status"] == "DRAFT"
    with Session(engine) as session:
        event_record = session.scalar(
            select(AuditEvent).where(AuditEvent.entity_id == requisition["requisition_id"])
        )
        assert event_record is not None
        assert event_record.actor_type == "USER"
        assert event_record.actor_id == "USR-RECRUITMENT-TEST"


def test_requisition_validation_and_status_cannot_be_set_by_client(client, engine) -> None:
    manager = client.post("/api/v1/hiring-managers", json=manager_payload()).json()
    payload = {
        "hiring_manager_id": manager["hiring_manager_id"],
        "title": "Invalid compensation",
        "department": "Engineering",
        "job_family": "Software",
        "location": "Remote",
        "employment_type": "FULL_TIME",
        "work_mode": "REMOTE",
        "opening_date": "2026-01-01",
        "min_salary": 150000,
        "max_salary": 100000,
    }
    assert client.post("/api/v1/requisitions", json=payload).status_code == 422
    payload["max_salary"] = 200000
    payload["status"] = "OPEN"
    assert client.post("/api/v1/requisitions", json=payload).status_code == 422
    assert client.get("/api/v1/requisitions/does-not-exist").status_code == 404


def test_requisition_creation_rejects_missing_or_inactive_manager(client, engine) -> None:
    payload = {
        "hiring_manager_id": "HM-MISSING",
        "title": "Backend Engineer",
        "department": "Engineering",
        "job_family": "Software",
        "location": "Remote",
        "employment_type": "FULL_TIME",
        "work_mode": "REMOTE",
        "opening_date": "2026-01-01",
    }
    missing = client.post("/api/v1/requisitions", json=payload)
    assert missing.status_code == 422

    with Session(engine) as session, session.begin():
        session.add(
            HiringManager(
                hiring_manager_id="HM-INACTIVE",
                employee_code="hm-inactive",
                name="Inactive Manager",
                email="inactive@example.invalid",
                department="Engineering",
                active_status="INACTIVE",
            )
        )
    payload["hiring_manager_id"] = "HM-INACTIVE"
    inactive = client.post("/api/v1/requisitions", json=payload)
    assert inactive.status_code == 422
    assert client.get("/api/v1/hiring-managers?active_only=true").json() == []
    assert client.get("/api/v1/hiring-managers").json()[0]["active_status"] == "INACTIVE"


def test_requisition_approval_workflow_and_opening_gate(client, engine) -> None:
    manager = client.post("/api/v1/hiring-managers", json=manager_payload()).json()
    created = client.post(
        "/api/v1/requisitions",
        json={
            "hiring_manager_id": manager["hiring_manager_id"],
            "title": "Approved Backend Engineer",
            "department": "Engineering",
            "job_family": "Software",
            "location": "Remote",
            "employment_type": "FULL_TIME",
            "work_mode": "REMOTE",
            "headcount": 1,
            "min_salary": 100000,
            "max_salary": 150000,
            "currency_code": "USD",
            "compensation_period": "YEAR",
            "opening_date": "2026-01-01",
        },
    )
    assert created.status_code == 201
    requisition_id = created.json()["requisition_id"]

    approvers = client.get(
        f"/api/v1/requisitions/{requisition_id}/approvers"
    )
    assert approvers.status_code == 200
    assert approvers.json() == [
        {"user_id": "USR-APPROVER-TEST", "display_name": "Test Approver"}
    ]

    submission = {
        "approvals": [
            {
                "approval_stage": "DIRECTOR",
                "approval_sequence": 1,
                "approver_id": "USR-APPROVER-TEST",
            }
        ],
        "reason": "The requisition is complete and ready for review.",
    }
    submitted = client.post(
        f"/api/v1/requisitions/{requisition_id}/submit-for-approval",
        json=submission,
    )
    assert submitted.status_code == 200
    assert submitted.json()[0]["decision"] == "PENDING"
    assert client.get(
        f"/api/v1/requisitions/{requisition_id}"
    ).json()["status"] == "PENDING_APPROVAL"

    sign_in_as(client, "approver@example.invalid", "approver test password")
    approvals = client.get(f"/api/v1/requisitions/{requisition_id}/approvals")
    assert approvals.status_code == 200
    approval_id = approvals.json()[0]["requisition_approval_id"]
    decision = client.post(
        f"/api/v1/requisition-approvals/{approval_id}/decision",
        json={"decision": "APPROVED", "comments": "Approved."},
    )
    assert decision.status_code == 200
    assert decision.json()["decision"] == "APPROVED"
    duplicate_decision = client.post(
        f"/api/v1/requisition-approvals/{approval_id}/decision",
        json={"decision": "REJECTED", "comments": "Changed my mind."},
    )
    assert duplicate_decision.status_code == 409

    sign_in_as(client, "recruiter@example.invalid", "recruitment test password")
    opened = client.post(
        f"/api/v1/requisitions/{requisition_id}/open",
        json={"reason": "Required approval is complete."},
    )
    assert opened.status_code == 200
    assert opened.json()["status"] == "OPEN"
    with Session(engine) as session:
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.related_entity_id == requisition_id
                )
            )
        )
        assert any(
            event.event_type == "APPROVAL_DECISION"
            and event.actor_id == "USR-APPROVER-TEST"
            for event in events
        )


def test_requisition_approval_rejects_requester_and_requires_reason(client) -> None:
    manager = client.post("/api/v1/hiring-managers", json=manager_payload()).json()
    created = client.post(
        "/api/v1/requisitions",
        json={
            "hiring_manager_id": manager["hiring_manager_id"],
            "title": "Approval Validation Engineer",
            "department": "Engineering",
            "job_family": "Software",
            "location": "Remote",
            "employment_type": "FULL_TIME",
            "work_mode": "REMOTE",
            "opening_date": "2026-01-01",
        },
    ).json()
    requisition_id = created["requisition_id"]
    invalid = client.post(
        f"/api/v1/requisitions/{requisition_id}/submit-for-approval",
        json={
            "approvals": [
                {
                    "approval_stage": "DIRECTOR",
                    "approval_sequence": 1,
                    "approver_id": "USR-RECRUITMENT-TEST",
                }
            ],
            "reason": "Submit",
        },
    )
    assert invalid.status_code == 422
    no_reason = client.post(
        f"/api/v1/requisitions/{requisition_id}/submit-for-approval",
        json={
            "approvals": [
                {
                    "approval_stage": "DIRECTOR",
                    "approval_sequence": 1,
                    "approver_id": "USR-APPROVER-TEST",
                }
            ],
            "reason": " ",
        },
    )
    assert no_reason.status_code == 422
    assert client.get(
        f"/api/v1/requisitions/{requisition_id}"
    ).json()["status"] == "DRAFT"


def test_department_scoped_recruiter_cannot_read_other_requisitions(client, engine) -> None:
    manager = client.post("/api/v1/hiring-managers", json=manager_payload()).json()
    requisition_ids = {}
    for department in ("Engineering", "Finance"):
        response = client.post(
            "/api/v1/requisitions",
            json={
                "hiring_manager_id": manager["hiring_manager_id"],
                "title": f"{department} Analyst",
                "department": department,
                "job_family": "Operations",
                "location": "Remote",
                "employment_type": "FULL_TIME",
                "work_mode": "REMOTE",
                "opening_date": "2026-01-01",
            },
        )
        assert response.status_code == 201
        requisition_ids[department] = response.json()["requisition_id"]

    with Session(engine, expire_on_commit=False) as session, session.begin():
        role = session.scalar(select(Role).where(Role.role_code == "RECRUITER"))
        assert role is not None
        scoped_user = User(
            user_id="USR-FINANCE-RECRUITER",
            email="finance.recruiter@example.invalid",
            display_name="Finance Recruiter",
            password_hash=hash_password("finance recruiter password"),
            status="ACTIVE",
        )
        session.add(scoped_user)
        session.flush()
        session.add(
            UserRole(
                user_id=scoped_user.user_id,
                role_id=role.role_id,
                scope_type="DEPARTMENT",
                scope_department="Finance",
            )
        )

    sign_in_as(client, "finance.recruiter@example.invalid", "finance recruiter password")
    listed = client.get("/api/v1/requisitions")
    assert listed.status_code == 200
    assert [item["department"] for item in listed.json()] == ["Finance"]
    assert client.get(
        f"/api/v1/requisitions/{requisition_ids['Finance']}"
    ).status_code == 200
    assert client.get(
        f"/api/v1/requisitions/{requisition_ids['Engineering']}"
    ).status_code == 404


def test_admin_can_provision_pending_staff_account_with_explicit_profile_and_role(client) -> None:
    manager = client.post("/api/v1/hiring-managers", json=manager_payload()).json()
    roles = client.get("/api/v1/roles")
    assert roles.status_code == 200
    assert {role["role_code"] for role in roles.json()} == {
        "ADMIN",
        "RECRUITER",
        "HIRING_MANAGER",
        "INTERVIEWER",
        "APPROVER",
    }

    created = client.post(
        "/api/v1/users",
        json={
            "email": "new.manager@example.invalid",
            "display_name": "New Manager",
            "hiring_manager_id": manager["hiring_manager_id"],
            "role_grants": [
                {
                    "role_code": "HIRING_MANAGER",
                    "scope_type": "RESOURCE",
                }
            ],
        },
    )
    assert created.status_code == 201
    account = created.json()
    assert account["email"] == "new.manager@example.invalid"
    assert account["status"] == "PENDING_ACTIVATION"
    assert account["hiring_manager_id"] == manager["hiring_manager_id"]
    assert account["role_grants"] == [
        {
            "role_code": "HIRING_MANAGER",
            "scope_type": "RESOURCE",
            "scope_department": None,
            "scope_requisition_id": None,
        }
    ]
    assert "password_hash" not in account
    assert client.post(
        "/api/v1/auth/login",
        json={"email": account["email"], "password": "no password assigned"},
    ).status_code == 401

    duplicate = client.post(
        "/api/v1/users",
        json={"email": "NEW.MANAGER@example.invalid", "display_name": "Duplicate"},
    )
    assert duplicate.status_code == 409
    assert client.get("/api/v1/users").status_code == 200


def test_admin_provisioning_does_not_assign_a_role_implicitly(client) -> None:
    created = client.post(
        "/api/v1/users",
        json={
            "email": "no.role@example.invalid",
            "display_name": "No Role",
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "PENDING_ACTIVATION"
    assert created.json()["role_grants"] == []


def test_candidate_create_search_detail_and_duplicate_error(client, engine) -> None:
    response = client.post("/api/v1/candidates", json=candidate_payload("Jane@Example.Invalid"))
    assert response.status_code == 201
    candidate = response.json()
    assert candidate["email"] == "jane@example.invalid"
    assert candidate["skills"] == ["python", "sql"]
    assert client.get("/api/v1/candidates", params={"search": "JANE"}).json()[0]["candidate_id"] == candidate["candidate_id"]
    assert client.get(f"/api/v1/candidates/{candidate['candidate_id']}").json()["total_experience_months"] == 72
    assert client.post("/api/v1/candidates", json=candidate_payload()).status_code == 409
    assert client.post("/api/v1/candidates", json={**candidate_payload(), "email": "invalid"}).status_code == 422
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Candidate)) == 1


def test_application_create_valid_transition_and_history(client, engine) -> None:
    add_open_requisition(engine)
    candidate = client.post("/api/v1/candidates", json=candidate_payload()).json()
    response = client.post(
        "/api/v1/applications",
        json={
            "candidate_id": candidate["candidate_id"],
            "requisition_id": "REQ-OPEN",
            "source_channel": "REFERRAL",
        },
    )
    assert response.status_code == 201
    application = response.json()
    assert application["current_stage"] == "APPLIED"
    details = client.get(f"/api/v1/applications/{application['application_id']}").json()
    assert details["allowed_next_stages"] == ["SCREENING", "REJECTED", "WITHDRAWN"]

    transition = client.post(
        f"/api/v1/applications/{application['application_id']}/transition",
        json={"new_stage": "SCREENING", "reason": "Resume meets the screening criteria."},
    )
    assert transition.status_code == 200
    assert transition.json()["current_stage"] == "SCREENING"
    assert len(transition.json()["stage_history"]) == 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ApplicationStageHistory)) == 2


def test_invalid_application_transitions_and_closed_requisitions_are_rejected(client, engine) -> None:
    add_manager(engine)
    with Session(engine) as session, session.begin():
        session.add(
            Requisition(
                requisition_id="REQ-DRAFT",
                hiring_manager_id="HM-1",
                title="Not open",
                department="Engineering",
                job_family="Software",
                location="Remote",
                employment_type="FULL_TIME",
                work_mode="REMOTE",
                headcount=1,
                status="DRAFT",
                opening_date=date(2026, 1, 1),
            )
        )
    candidate = client.post("/api/v1/candidates", json=candidate_payload()).json()
    rejected = client.post(
        "/api/v1/applications",
        json={"candidate_id": candidate["candidate_id"], "requisition_id": "REQ-DRAFT"},
    )
    assert rejected.status_code == 409
    missing = client.post(
        "/api/v1/applications/not-an-id/transition",
        json={"new_stage": "SCREENING", "reason": "Test"},
    )
    assert missing.status_code == 404


def test_dashboard_reflects_database_counts(client, engine) -> None:
    add_open_requisition(engine)
    candidate = client.post("/api/v1/candidates", json=candidate_payload()).json()
    client.post(
        "/api/v1/applications",
        json={"candidate_id": candidate["candidate_id"], "requisition_id": "REQ-OPEN"},
    )
    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["total_requisitions"] == 1
    assert dashboard["open_requisitions"] == 1
    assert dashboard["total_candidates"] == 1
    assert dashboard["total_applications"] == 1
    assert dashboard["applications_by_stage"]["APPLIED"] == 1
    assert dashboard["recent_applications"][0]["candidate_name"] == "Jane Candidate"
