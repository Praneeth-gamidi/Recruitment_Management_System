from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.base import Base
from src.generators.master_data_generator import TABLE_NAMES as RECRUITMENT_TABLE_NAMES
from src.models import (
    Application,
    ApplicationStageHistory,
    Approval,
    Availability,
    Candidate,
    EvaluationCriterion,
    HiringManager,
    Interview,
    InterviewPanel,
    InterviewRescheduleHistory,
    Interviewer,
    Offer,
    PanelInterviewer,
    Requisition,
    RequisitionApproval,
    Scorecard,
    ScorecardCriteria,
)
from src.services.requisition_service import transition_requisition
from src.services.approval_service import decide_offer_approval, decide_requisition_approval
from src.services.offer_service import transition_offer
from src.services.evaluation_service import submit_scorecard
from src.services.application_service import create_application, transition_application


@pytest.fixture
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def add_requisition(session: Session, *, min_salary: Decimal = Decimal("70000.00"),
                    max_salary: Decimal = Decimal("100000.00"), status: str = "DRAFT") -> Requisition:
    manager = HiringManager(
        hiring_manager_id="HM-1",
        employee_code="emp-1",
        name="Hiring Manager",
        email="manager@example.invalid",
        department="Engineering",
    )
    requisition = Requisition(
        requisition_id="REQ-1",
        hiring_manager=manager,
        title="Engineer",
        department="Engineering",
        job_family="SOFTWARE",
        location="Remote",
        employment_type="FULL_TIME",
        work_mode="REMOTE",
        headcount=1,
        status=status,
        min_salary=min_salary,
        max_salary=max_salary,
        currency_code="USD",
        compensation_period="YEAR",
        opening_date=date.today(),
    )
    session.add(requisition)
    session.flush()
    return requisition


def add_application(session: Session, requisition: Requisition) -> Application:
    candidate = Candidate(
        candidate_id="CAND-1",
        first_name="Casey",
        last_name="Candidate",
        email="casey@example.invalid",
    )
    application = Application(
        application_id="APP-1",
        candidate=candidate,
        requisition=requisition,
        source_channel="CAREER_SITE",
    )
    session.add(application)
    session.flush()
    return application


def add_interview(session: Session, application: Application) -> Interview:
    panel = InterviewPanel(panel_id="PANEL-1", panel_name="Engineering", panel_type="TECHNICAL")
    interview = Interview(
        interview_id="INT-1",
        application=application,
        panel=panel,
        interview_round=1,
        interview_type="TECHNICAL",
        start_at=datetime.now(timezone.utc),
        end_at=datetime.now(timezone.utc) + timedelta(minutes=60),
        duration_minutes=60,
    )
    session.add(interview)
    session.flush()
    return interview


def test_all_models_register_and_create_tables(session: Session) -> None:
    expected_tables = set(Base.metadata.tables)
    auth_tables = {
        "users",
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
        "refresh_tokens",
        "account_action_tokens",
    }
    assert len(Base.registry.mappers) == 28
    assert len(expected_tables) == 28
    assert expected_tables == set(RECRUITMENT_TABLE_NAMES) | auth_tables
    assert set(inspect(session.get_bind()).get_table_names()) == expected_tables


def test_primary_and_unique_constraints(session: Session) -> None:
    session.add_all(
        [
            HiringManager(
                hiring_manager_id="HM-1", employee_code="emp-1", name="One",
                email="one@example.invalid", department="HR",
            ),
            HiringManager(
                hiring_manager_id="HM-2", employee_code="emp-1", name="Two",
                email="two@example.invalid", department="HR",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_primary_key_uniqueness(session: Session) -> None:
    session.add_all(
        [
            HiringManager(
                hiring_manager_id="HM-1", employee_code="emp-1", name="One",
                email="one@example.invalid", department="HR",
            ),
            HiringManager(
                hiring_manager_id="HM-1", employee_code="emp-2", name="Two",
                email="two@example.invalid", department="HR",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_foreign_key_integrity(session: Session) -> None:
    session.add(
        Application(
            application_id="APP-INVALID",
            candidate_id="MISSING",
            requisition_id="MISSING",
            source_channel="CAREER_SITE",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_invalid_compensation_range_is_rejected(session: Session) -> None:
    with pytest.raises(IntegrityError):
        add_requisition(session, min_salary=Decimal("120000"), max_salary=Decimal("80000"))


def test_duplicate_candidate_requisition_application_is_rejected(session: Session) -> None:
    requisition = add_requisition(session)
    first = add_application(session, requisition)
    duplicate = Application(
        application_id="APP-2",
        candidate_id=first.candidate_id,
        requisition_id=requisition.requisition_id,
        source_channel="REFERRAL",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()


def test_invalid_lifecycle_values_are_rejected(session: Session) -> None:
    requisition = add_requisition(session)
    session.add(
        Application(
            application_id="APP-1",
            candidate_id="CAND-1",
            requisition_id=requisition.requisition_id,
            current_stage="INTERVIEW",
            source_channel="CAREER_SITE",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_invalid_interview_interval_is_rejected(session: Session) -> None:
    requisition = add_requisition(session)
    application = add_application(session, requisition)
    now = datetime.now(timezone.utc)
    session.add(
        Interview(
            interview_id="INT-BAD",
            application=application,
            panel=InterviewPanel(panel_id="PANEL-1", panel_name="Panel"),
            interview_round=1,
            interview_type="TECHNICAL",
            start_at=now + timedelta(hours=2),
            end_at=now + timedelta(hours=1),
            duration_minutes=60,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_score_rating_outside_scale_is_rejected(session: Session) -> None:
    requisition = add_requisition(session)
    interview = add_interview(session, add_application(session, requisition))
    reviewer = Interviewer(
        interviewer_id="INTV-1",
        employee_code="emp-2",
        name="Reviewer",
        email="reviewer@example.invalid",
        department="Engineering",
        designation="Engineer",
    )
    criterion = EvaluationCriterion(
        criterion_id="CRIT-1",
        criterion_code="TECH",
        criterion_name="Technical",
        description="Technical skill",
        effective_from=date.today(),
    )
    scorecard = Scorecard(
        scorecard_id="SCORE-1",
        interview=interview,
        reviewer=reviewer,
        completion_status="DRAFT",
    )
    session.add(
        ScorecardCriteria(
            scorecard_criteria_id="SC-1",
            scorecard=scorecard,
            criterion=criterion,
            rating=6,
            criterion_name_snapshot="Technical",
            weight_snapshot=Decimal("1.000"),
            maximum_rating_snapshot=5,
            mandatory_snapshot=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_approval_and_history_relationships(session: Session) -> None:
    requisition = add_requisition(session)
    requisition_approval = RequisitionApproval(
        requisition_approval_id="REQAPP-1",
        requisition_id=requisition.requisition_id,
        approver_id="approver-1",
        approval_sequence=1,
        approval_stage="FINANCE",
    )
    application = add_application(session, requisition)
    history = ApplicationStageHistory(
        stage_history_id="STAGE-1",
        application_id=application.application_id,
        history_sequence=1,
        new_stage="APPLIED",
        new_status="ACTIVE",
        actor_id="system",
        actor_name_snapshot="System",
        reason="Application submitted",
    )
    interview = add_interview(session, application)
    reschedule = InterviewRescheduleHistory(
        reschedule_history_id="RESCHED-1",
        interview_id=interview.interview_id,
        reschedule_sequence=1,
        previous_start_at=interview.start_at,
        previous_end_at=interview.end_at,
        new_start_at=interview.start_at + timedelta(days=1),
        new_end_at=interview.end_at + timedelta(days=1),
        actor_id="scheduler",
        actor_name_snapshot="Scheduler",
        reason="Interviewer requested a new time",
    )
    offer = Offer(
        offer_id="OFF-1",
        application_id=application.application_id,
        offer_version=1,
        proposed_salary=Decimal("90000"),
        band_min_snapshot=Decimal("70000"),
        band_max_snapshot=Decimal("100000"),
        currency_code="USD",
        compensation_period="YEAR",
        created_by="recruiter",
    )
    offer_approval = Approval(
        approval_id="APPROVAL-1",
        offer_id=offer.offer_id,
        approval_sequence=1,
        approval_stage="FINANCE",
        approver_id="approver-2",
        approver_name_snapshot="Finance",
        approver_role="FINANCE",
    )
    session.add_all([requisition_approval, history, reschedule, offer, offer_approval])
    session.flush()
    assert requisition.approvals[0].requisition_approval_id == "REQAPP-1"
    assert application.stage_history[0].stage_history_id == "STAGE-1"
    assert interview.reschedule_history[0].reschedule_history_id == "RESCHED-1"
    assert offer.approvals[0].approval_id == "APPROVAL-1"


def test_scheduling_requires_full_availability_for_each_panel_member(session: Session) -> None:
    application = add_application(session, add_requisition(session))
    panel = InterviewPanel(panel_id="PANEL-1", panel_name="Engineering", panel_type="TECHNICAL")
    interviewer = Interviewer(
        interviewer_id="INTV-1",
        employee_code="emp-2",
        name="Reviewer",
        email="reviewer@example.invalid",
        department="Engineering",
        designation="Engineer",
    )
    start_at = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(days=1)
    session.add_all(
        [
            panel,
            interviewer,
            PanelInterviewer(
                panel_interviewer_id="MEMBER-1",
                panel=panel,
                interviewer=interviewer,
                role_in_panel="LEAD",
                effective_from=start_at.date(),
            ),
            Availability(
                availability_id="AVAIL-1",
                interviewer=interviewer,
                available_start=start_at,
                available_end=start_at + timedelta(minutes=60),
                availability_status="AVAILABLE",
            ),
        ]
    )
    session.flush()
    interview = Interview(
        interview_id="INT-1",
        application_id=application.application_id,
        panel_id=panel.panel_id,
        interview_round=1,
        interview_type="TECHNICAL",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=60),
        duration_minutes=60,
    )
    from src.services.interview_service import schedule_interview

    scheduled = schedule_interview(session, interview)
    assert scheduled.interview_id == "INT-1"


def test_scheduling_rejects_a_panel_member_without_availability(session: Session) -> None:
    application = add_application(session, add_requisition(session))
    panel = InterviewPanel(panel_id="PANEL-1", panel_name="Engineering", panel_type="TECHNICAL")
    interviewer = Interviewer(
        interviewer_id="INTV-1",
        employee_code="emp-2",
        name="Reviewer",
        email="reviewer@example.invalid",
        department="Engineering",
        designation="Engineer",
    )
    start_at = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(days=1)
    session.add_all(
        [
            panel,
            interviewer,
            PanelInterviewer(
                panel_interviewer_id="MEMBER-1",
                panel=panel,
                interviewer=interviewer,
                role_in_panel="LEAD",
                effective_from=start_at.date(),
            ),
        ]
    )
    session.flush()
    interview = Interview(
        interview_id="INT-1",
        application_id=application.application_id,
        panel_id=panel.panel_id,
        interview_round=1,
        interview_type="TECHNICAL",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=60),
        duration_minutes=60,
    )
    from src.services.interview_service import schedule_interview

    with pytest.raises(ValueError, match="must be available"):
        schedule_interview(session, interview)


def test_requisition_open_requires_approved_current_cycle(session: Session) -> None:
    requisition = add_requisition(session, status="PENDING_APPROVAL")
    session.add(
        RequisitionApproval(
            requisition_approval_id="REQAPP-1",
            requisition=requisition,
            approver_id="approver-1",
            approval_cycle=1,
            approval_sequence=1,
            approval_stage="FINANCE",
        )
    )
    session.flush()
    with pytest.raises(ValueError, match="incomplete or not fully approved"):
        transition_requisition(
            session,
            "REQ-1",
            "OPEN",
            required_approval_stages={"FINANCE"},
            actor_id="actor-1",
            actor_name_snapshot="Actor",
            reason="Open requisition",
        )
    approval = session.get(RequisitionApproval, "REQAPP-1")
    approval.decision = "APPROVED"
    approval.decided_at = datetime.now(timezone.utc)
    session.flush()
    opened = transition_requisition(
        session,
        "REQ-1",
        "OPEN",
        required_approval_stages={"FINANCE"},
        actor_id="actor-1",
        actor_name_snapshot="Actor",
        reason="Open requisition",
    )
    assert opened.status == "OPEN"
    assert opened.approved_at is not None


def test_requisition_approval_decision_is_immutable(session: Session) -> None:
    requisition = add_requisition(session, status="PENDING_APPROVAL")
    session.add(
        RequisitionApproval(
            requisition_approval_id="REQAPP-1",
            requisition_id=requisition.requisition_id,
            approver_id="approver-1",
            approval_sequence=1,
            approval_stage="FINANCE",
        )
    )
    session.flush()
    decision = decide_requisition_approval(
        session,
        "REQAPP-1",
        "APPROVED",
        actor_id="approver-1",
        actor_name_snapshot="Finance Approver",
    )
    assert decision.decision == "APPROVED"
    with pytest.raises(ValueError, match="immutable"):
        decide_requisition_approval(
            session,
            "REQAPP-1",
            "REJECTED",
            actor_id="approver-1",
            actor_name_snapshot="Finance Approver",
            comments="Changed mind",
        )


def test_offer_progression_requires_approved_workflow(session: Session) -> None:
    application = add_application(session, add_requisition(session))
    offer = Offer(
        offer_id="OFF-1",
        application_id=application.application_id,
        offer_version=1,
        proposed_salary=Decimal("90000"),
        band_min_snapshot=Decimal("70000"),
        band_max_snapshot=Decimal("100000"),
        currency_code="USD",
        compensation_period="YEAR",
        offer_date=date.today(),
        joining_date=date.today() + timedelta(days=30),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_by="recruiter",
    )
    approval = Approval(
        approval_id="APPROVAL-1",
        offer=offer,
        approval_sequence=1,
        approval_stage="FINANCE",
        approver_id="approver-1",
        approver_name_snapshot="Finance Approver",
        approver_role="FINANCE",
    )
    session.add_all([offer, approval])
    session.flush()
    transition_offer(
        session,
        offer.offer_id,
        "PENDING_APPROVAL",
        actor_id="recruiter",
        actor_name_snapshot="Recruiter",
        reason="Submit offer for review",
    )
    with pytest.raises(ValueError, match="must be approved"):
        transition_offer(
            session,
            offer.offer_id,
            "APPROVED",
            required_approval_stages={"FINANCE"},
            actor_id="recruiter",
            actor_name_snapshot="Recruiter",
            reason="Approve offer",
        )
    decide_offer_approval(
        session,
        "APPROVAL-1",
        "APPROVED",
        actor_id="approver-1",
        actor_name_snapshot="Finance Approver",
    )
    transition_offer(
        session,
        offer.offer_id,
        "APPROVED",
        required_approval_stages={"FINANCE"},
        actor_id="recruiter",
        actor_name_snapshot="Recruiter",
        reason="Approvals complete",
    )
    sent = transition_offer(
        session,
        offer.offer_id,
        "SENT",
        required_approval_stages={"FINANCE"},
        actor_id="recruiter",
        actor_name_snapshot="Recruiter",
        reason="Send approved offer",
    )
    assert sent.sent_at is not None


def test_scorecard_submission_checks_panel_and_supports_explicit_revision(session: Session) -> None:
    interview = add_interview(
        session,
        add_application(session, add_requisition(session)),
    )
    interview.status = "COMPLETED"
    session.flush()
    reviewer = Interviewer(
        interviewer_id="INTV-1",
        employee_code="emp-2",
        name="Reviewer",
        email="reviewer@example.invalid",
        department="Engineering",
        designation="Engineer",
    )
    criterion = EvaluationCriterion(
        criterion_id="CRIT-1",
        criterion_code="TECH",
        criterion_name="Technical",
        description="Technical skill",
        effective_from=date.today(),
    )
    membership = PanelInterviewer(
        panel_interviewer_id="MEMBER-1",
        panel_id=interview.panel_id,
        interviewer_id=reviewer.interviewer_id,
        role_in_panel="LEAD",
        effective_from=interview.start_at.date(),
    )
    first = Scorecard(
        scorecard_id="SCORE-1",
        interview_id=interview.interview_id,
        reviewer_id=reviewer.interviewer_id,
        revision_no=1,
    )
    first_criterion = ScorecardCriteria(
        scorecard_criteria_id="SC-1",
        scorecard_id=first.scorecard_id,
        criterion_id=criterion.criterion_id,
        rating=5,
        criterion_name_snapshot=criterion.criterion_name,
        weight_snapshot=Decimal("1.000"),
        maximum_rating_snapshot=5,
        mandatory_snapshot=True,
    )
    session.add_all([reviewer, criterion, membership, first, first_criterion])
    session.flush()
    submitted = submit_scorecard(
        session,
        first.scorecard_id,
        reviewer_id=reviewer.interviewer_id,
        required_criterion_ids={"CRIT-1"},
    )
    assert submitted.completion_status == "SUBMITTED"
    assert submitted.overall_score == Decimal("5.000")
    assert submitted.recommendation == "STRONG_HIRE"

    second = Scorecard(
        scorecard_id="SCORE-2",
        interview_id=interview.interview_id,
        reviewer_id=reviewer.interviewer_id,
        supersedes_scorecard_id=first.scorecard_id,
        revision_no=2,
    )
    second_criterion = ScorecardCriteria(
        scorecard_criteria_id="SC-2",
        scorecard_id=second.scorecard_id,
        criterion_id=criterion.criterion_id,
        rating=4,
        criterion_name_snapshot=criterion.criterion_name,
        weight_snapshot=Decimal("1.000"),
        maximum_rating_snapshot=5,
        mandatory_snapshot=True,
    )
    session.add_all([second, second_criterion])
    session.flush()
    submit_scorecard(
        session,
        second.scorecard_id,
        reviewer_id=reviewer.interviewer_id,
        required_criterion_ids={"CRIT-1"},
    )
    assert first.completion_status == "SUPERSEDED"
    assert second.completion_status == "SUBMITTED"


def test_application_transition_appends_stage_history_and_audit(session: Session) -> None:
    application = add_application(session, add_requisition(session))
    transitioned = transition_application(
        session,
        application.application_id,
        actor_id="recruiter-1",
        actor_name_snapshot="Recruiter",
        reason="Initial screening passed",
        new_stage="SCREENING",
    )
    assert transitioned.current_stage == "SCREENING"
    assert transitioned.stage_history[0].previous_stage == "APPLIED"
    assert transitioned.stage_history[0].new_stage == "SCREENING"
    assert transitioned.stage_history[0].reason == "Initial screening passed"

    closed = transition_application(
        session,
        application.application_id,
        actor_id="recruiter-1",
        actor_name_snapshot="Recruiter",
        reason="Candidate withdrew",
        new_stage="WITHDRAWN",
    )
    assert closed.status == "CLOSED"
    with pytest.raises(ValueError, match="terminal"):
        transition_application(
            session,
            application.application_id,
            actor_id="recruiter-1",
            actor_name_snapshot="Recruiter",
            reason="Try reopening",
            new_stage="APPLIED",
        )


def test_application_creation_records_initial_history(session: Session) -> None:
    requisition = add_requisition(session, status="OPEN")
    candidate = Candidate(
        candidate_id="CAND-1",
        first_name="Casey",
        last_name="Candidate",
        email="casey@example.invalid",
    )
    application = Application(
        application_id="APP-1",
        candidate=candidate,
        requisition=requisition,
        source_channel="CAREER_SITE",
    )
    created = create_application(
        session,
        application,
        actor_id="candidate-1",
        actor_name_snapshot="Casey Candidate",
        reason="Application submitted",
    )
    assert created.current_stage == "APPLIED"
    assert created.status == "ACTIVE"
    assert created.stage_history[0].previous_stage is None
    assert created.stage_history[0].previous_status is None
