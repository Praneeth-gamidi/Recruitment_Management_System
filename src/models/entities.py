from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
TIMESTAMP = DateTime(timezone=True)


class HiringManager(Base):
    __tablename__ = "hiring_managers"
    __table_args__ = (
        CheckConstraint("active_status IN ('ACTIVE', 'INACTIVE')", name="active_status"),
        CheckConstraint("employee_code = lower(employee_code)", name="employee_code_normalized"),
        CheckConstraint("email = lower(email)", name="email_normalized"),
    )

    hiring_manager_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    active_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    requisitions: Mapped[list[Requisition]] = relationship(back_populates="hiring_manager")


class Requisition(Base):
    __tablename__ = "requisitions"
    __table_args__ = (
        CheckConstraint(
            "employment_type IN ('FULL_TIME', 'PART_TIME', 'CONTRACT', 'TEMPORARY', 'INTERN')",
            name="employment_type",
        ),
        CheckConstraint("work_mode IN ('ONSITE', 'HYBRID', 'REMOTE')", name="work_mode"),
        CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'OPEN', 'ON_HOLD', 'FILLED', 'CLOSED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint("headcount > 0", name="headcount_positive"),
        CheckConstraint("min_salary IS NULL OR min_salary >= 0", name="min_salary_nonnegative"),
        CheckConstraint("max_salary IS NULL OR max_salary > 0", name="max_salary_positive"),
        CheckConstraint(
            "min_salary IS NULL OR max_salary IS NULL OR min_salary <= max_salary",
            name="salary_range",
        ),
        CheckConstraint(
            "compensation_period IS NULL OR compensation_period IN ('YEAR', 'MONTH', 'HOUR')",
            name="compensation_period",
        ),
        CheckConstraint("closing_date IS NULL OR opening_date <= closing_date", name="date_range"),
        Index("ix_requisitions_status_department", "status", "department"),
        Index("ix_requisitions_location_status", "location", "status"),
        Index("ix_requisitions_hiring_manager_id", "hiring_manager_id"),
        Index("ix_requisitions_closing_date", "closing_date"),
    )

    requisition_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    hiring_manager_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("hiring_managers.hiring_manager_id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    job_family: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str] = mapped_column(String(160), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    work_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    headcount: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="DRAFT")
    min_salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency_code: Mapped[str | None] = mapped_column(CHAR(3))
    compensation_period: Mapped[str | None] = mapped_column(String(12))
    opening_date: Mapped[date] = mapped_column(Date, nullable=False)
    closing_date: Mapped[date | None] = mapped_column(Date)
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    hiring_manager: Mapped[HiringManager] = relationship(back_populates="requisitions")
    approvals: Mapped[list[RequisitionApproval]] = relationship(back_populates="requisition")
    skill_requirements: Mapped[list[SkillRequirement]] = relationship(back_populates="requisition")
    applications: Mapped[list[Application]] = relationship(back_populates="requisition")


class RequisitionApproval(Base):
    __tablename__ = "requisition_approvals"
    __table_args__ = (
        UniqueConstraint("requisition_id", "approval_cycle", "approval_sequence"),
        CheckConstraint("approval_cycle >= 1", name="approval_cycle_positive"),
        CheckConstraint("approval_sequence >= 1", name="approval_sequence_positive"),
        CheckConstraint(
            "decision IN ('PENDING', 'APPROVED', 'REJECTED', 'RETURNED_FOR_REVISION')",
            name="decision",
        ),
        CheckConstraint(
            "(decision = 'PENDING' AND decided_at IS NULL) OR "
            "(decision <> 'PENDING' AND decided_at IS NOT NULL)",
            name="decision_timestamp",
        ),
        CheckConstraint(
            "decision NOT IN ('REJECTED', 'RETURNED_FOR_REVISION') OR "
            "(comments IS NOT NULL AND length(trim(comments)) > 0)",
            name="decision_comment_required",
        ),
        Index("ix_requisition_approvals_cycle_decision", "requisition_id", "approval_cycle", "decision"),
        Index("ix_requisition_approvals_approver_decided", "approver_id", "decided_at"),
        Index("ix_requisition_approvals_supersedes_id", "supersedes_requisition_approval_id"),
    )

    requisition_approval_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    requisition_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("requisitions.requisition_id", ondelete="RESTRICT"), nullable=False
    )
    approver_id: Mapped[str] = mapped_column(String(80), nullable=False)
    approval_cycle: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    approval_sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    approval_stage: Mapped[str] = mapped_column(String(80), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False, server_default="PENDING")
    comments: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    supersedes_requisition_approval_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("requisition_approvals.requisition_approval_id", ondelete="RESTRICT")
    )

    requisition: Mapped[Requisition] = relationship(back_populates="approvals")
    supersedes: Mapped[RequisitionApproval | None] = relationship(
        remote_side="RequisitionApproval.requisition_approval_id", back_populates="superseded_by"
    )
    superseded_by: Mapped[list[RequisitionApproval]] = relationship(back_populates="supersedes")


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint(
            "education_level IS NULL OR education_level IN "
            "('SECONDARY', 'ASSOCIATE', 'BACHELOR', 'MASTER', 'DOCTORATE', 'OTHER')",
            name="education_level",
        ),
        CheckConstraint("email = lower(email)", name="email_normalized"),
        CheckConstraint("total_experience_months >= 0", name="experience_nonnegative"),
    )

    candidate_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[str | None] = mapped_column(String(160))
    education_level: Mapped[str | None] = mapped_column(String(24))
    education_summary: Mapped[str | None] = mapped_column(String(500))
    total_experience_months: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    profile_created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    applications: Mapped[list[Application]] = relationship(back_populates="candidate")
    skills: Mapped[list[CandidateSkill]] = relationship(back_populates="candidate")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_id", "requisition_id"),
        CheckConstraint(
            "current_stage IN ('APPLIED', 'SCREENING', 'ASSESSMENT', 'TECHNICAL_INTERVIEW', "
            "'MANAGERIAL_INTERVIEW', 'HR_INTERVIEW', 'OFFER', 'HIRED', 'REJECTED', 'WITHDRAWN')",
            name="current_stage",
        ),
        CheckConstraint("status IN ('ACTIVE', 'ON_HOLD', 'CLOSED')", name="status"),
        CheckConstraint(
            "(current_stage IN ('HIRED', 'REJECTED', 'WITHDRAWN') AND status = 'CLOSED') OR "
            "(current_stage NOT IN ('HIRED', 'REJECTED', 'WITHDRAWN') AND status IN ('ACTIVE', 'ON_HOLD'))",
            name="stage_status_consistency",
        ),
        CheckConstraint(
            "source_channel IN ('CAREER_SITE', 'REFERRAL', 'JOB_BOARD', 'AGENCY', 'DIRECT', 'OTHER')",
            name="source_channel",
        ),
        Index("ix_applications_requisition_applied", "requisition_id", "applied_at"),
        Index("ix_applications_stage_status", "current_stage", "status"),
        Index("ix_applications_status_updated", "status", "updated_at"),
    )

    application_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("candidates.candidate_id", ondelete="RESTRICT"), nullable=False
    )
    requisition_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("requisitions.requisition_id", ondelete="RESTRICT"), nullable=False
    )
    applied_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    current_stage: Mapped[str] = mapped_column(String(32), nullable=False, server_default="APPLIED")
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="ACTIVE")
    source_channel: Mapped[str] = mapped_column(String(32), nullable=False, server_default="CAREER_SITE")
    source_detail: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    candidate: Mapped[Candidate] = relationship(back_populates="applications")
    requisition: Mapped[Requisition] = relationship(back_populates="applications")
    interviews: Mapped[list[Interview]] = relationship(back_populates="application")
    offers: Mapped[list[Offer]] = relationship(back_populates="application")
    stage_history: Mapped[list[ApplicationStageHistory]] = relationship(back_populates="application")


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint("active_status IN ('ACTIVE', 'INACTIVE')", name="active_status"),
        CheckConstraint("skill_name = lower(skill_name)", name="skill_name_normalized"),
    )

    skill_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    skill_category: Mapped[str | None] = mapped_column(String(40))
    active_status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    requirements: Mapped[list[SkillRequirement]] = relationship(back_populates="skill")
    candidate_skills: Mapped[list[CandidateSkill]] = relationship(back_populates="skill")


class SkillRequirement(Base):
    __tablename__ = "skill_requirements"
    __table_args__ = (
        UniqueConstraint("requisition_id", "skill_id"),
        CheckConstraint("requirement_type IN ('MANDATORY', 'PREFERRED')", name="requirement_type"),
        CheckConstraint("minimum_proficiency BETWEEN 1 AND 5", name="minimum_proficiency"),
        CheckConstraint("minimum_experience_months >= 0", name="minimum_experience_nonnegative"),
        CheckConstraint("weight > 0", name="weight_positive"),
        Index("ix_skill_requirements_skill_type", "skill_id", "requirement_type"),
    )

    skill_requirement_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    requisition_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("requisitions.requisition_id", ondelete="RESTRICT"), nullable=False
    )
    skill_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("skills.skill_id", ondelete="RESTRICT"), nullable=False
    )
    requirement_type: Mapped[str] = mapped_column(String(12), nullable=False, server_default="MANDATORY")
    minimum_proficiency: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    minimum_experience_months: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    weight: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, server_default="1.000")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    requisition: Mapped[Requisition] = relationship(back_populates="skill_requirements")
    skill: Mapped[Skill] = relationship(back_populates="requirements")


class CandidateSkill(Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (
        UniqueConstraint("candidate_id", "skill_id"),
        CheckConstraint(
            "proficiency_level IN ('NOVICE', 'BEGINNER', 'INTERMEDIATE', 'ADVANCED', 'EXPERT')",
            name="proficiency_level",
        ),
        CheckConstraint("experience_months >= 0", name="experience_nonnegative"),
        Index("ix_candidate_skills_skill_proficiency", "skill_id", "proficiency_level"),
    )

    candidate_skill_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("candidates.candidate_id", ondelete="RESTRICT"), nullable=False
    )
    skill_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("skills.skill_id", ondelete="RESTRICT"), nullable=False
    )
    proficiency_level: Mapped[str] = mapped_column(String(16), nullable=False)
    experience_months: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_used_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    candidate: Mapped[Candidate] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship(back_populates="candidate_skills")


class InterviewPanel(Base):
    __tablename__ = "interview_panels"
    __table_args__ = (
        CheckConstraint("panel_type IN ('TECHNICAL', 'MANAGERIAL', 'HR', 'GENERAL')", name="panel_type"),
        CheckConstraint("active_status IN ('ACTIVE', 'INACTIVE')", name="active_status"),
    )

    panel_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    panel_name: Mapped[str] = mapped_column(String(120), nullable=False)
    panel_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="GENERAL")
    active_status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    interviews: Mapped[list[Interview]] = relationship(back_populates="panel")
    members: Mapped[list[PanelInterviewer]] = relationship(back_populates="panel")


class Interviewer(Base):
    __tablename__ = "interviewers"
    __table_args__ = (
        CheckConstraint("active_status IN ('ACTIVE', 'INACTIVE')", name="active_status"),
        CheckConstraint("employee_code = lower(employee_code)", name="employee_code_normalized"),
        CheckConstraint("email = lower(email)", name="email_normalized"),
    )

    interviewer_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    designation: Mapped[str] = mapped_column(String(100), nullable=False)
    active_status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[list[PanelInterviewer]] = relationship(back_populates="interviewer")
    availability: Mapped[list[Availability]] = relationship(back_populates="interviewer")
    scorecards: Mapped[list[Scorecard]] = relationship(back_populates="reviewer")


class PanelInterviewer(Base):
    __tablename__ = "panel_interviewers"
    __table_args__ = (
        UniqueConstraint("panel_id", "interviewer_id", "effective_from"),
        CheckConstraint(
            "role_in_panel IN ('LEAD', 'INTERVIEWER', 'OBSERVER', 'SPECIALIST')",
            name="role_in_panel",
        ),
        CheckConstraint("effective_to IS NULL OR effective_from <= effective_to", name="effective_dates"),
        Index("ix_panel_interviewers_interviewer_effective", "interviewer_id", "effective_from", "effective_to"),
        Index("ix_panel_interviewers_panel_effective", "panel_id", "effective_from", "effective_to"),
    )

    panel_interviewer_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    panel_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("interview_panels.panel_id", ondelete="RESTRICT"), nullable=False
    )
    interviewer_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("interviewers.interviewer_id", ondelete="RESTRICT"), nullable=False
    )
    role_in_panel: Mapped[str] = mapped_column(String(40), nullable=False, server_default="INTERVIEWER")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    panel: Mapped[InterviewPanel] = relationship(back_populates="members")
    interviewer: Mapped[Interviewer] = relationship(back_populates="memberships")


class Availability(Base):
    __tablename__ = "availability"
    __table_args__ = (
        UniqueConstraint("interviewer_id", "available_start", "available_end"),
        CheckConstraint("available_start < available_end", name="interval"),
        CheckConstraint(
            "availability_status IN ('AVAILABLE', 'UNAVAILABLE', 'BLOCKED')",
            name="availability_status",
        ),
        Index(
            "ix_availability_interviewer_window",
            "interviewer_id",
            "available_start",
            "available_end",
            "availability_status",
        ),
    )

    availability_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    interviewer_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("interviewers.interviewer_id", ondelete="RESTRICT"), nullable=False
    )
    available_start: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    available_end: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    availability_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="AVAILABLE")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    interviewer: Mapped[Interviewer] = relationship(back_populates="availability")


class Interview(Base):
    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint("interview_round >= 1", name="round_positive"),
        CheckConstraint(
            "interview_type IN ('SCREENING', 'ASSESSMENT', 'TECHNICAL', 'MANAGERIAL', 'HR', 'OTHER')",
            name="interview_type",
        ),
        CheckConstraint("start_at < end_at", name="interval"),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint(
            "status IN ('SCHEDULED', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'NO_SHOW')",
            name="status",
        ),
        CheckConstraint(
            "status <> 'CANCELLED' OR (cancellation_reason IS NOT NULL AND length(trim(cancellation_reason)) > 0)",
            name="cancellation_reason_required",
        ),
        Index("ix_interviews_status_window", "status", "start_at", "end_at"),
        Index("ix_interviews_application_start", "application_id", "start_at"),
        Index("ix_interviews_panel_start", "panel_id", "start_at"),
    )

    interview_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("applications.application_id", ondelete="RESTRICT"), nullable=False
    )
    panel_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("interview_panels.panel_id", ondelete="RESTRICT"), nullable=False
    )
    interview_round: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    interview_type: Mapped[str] = mapped_column(String(24), nullable=False)
    start_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    end_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="SCHEDULED")
    location: Mapped[str | None] = mapped_column(String(200))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    scheduled_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    application: Mapped[Application] = relationship(back_populates="interviews")
    panel: Mapped[InterviewPanel] = relationship(back_populates="interviews")
    scorecards: Mapped[list[Scorecard]] = relationship(back_populates="interview")
    reschedule_history: Mapped[list[InterviewRescheduleHistory]] = relationship(back_populates="interview")


class EvaluationCriterion(Base):
    __tablename__ = "evaluation_criteria"
    __table_args__ = (
        CheckConstraint("maximum_rating = 5", name="maximum_rating"),
        CheckConstraint("default_weight > 0", name="weight_positive"),
        CheckConstraint("criterion_code = upper(criterion_code)", name="criterion_code_normalized"),
        CheckConstraint(
            "applicability_scope IN ('ALL', 'DEPARTMENT', 'JOB_FAMILY', 'SKILL')",
            name="applicability_scope",
        ),
        CheckConstraint(
            "(applicability_scope = 'ALL' AND applicability_value IS NULL) OR "
            "(applicability_scope <> 'ALL' AND applicability_value IS NOT NULL)",
            name="applicability_value",
        ),
        CheckConstraint("active_status IN ('ACTIVE', 'INACTIVE')", name="active_status"),
        CheckConstraint("effective_to IS NULL OR effective_from <= effective_to", name="effective_dates"),
    )

    criterion_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    criterion_code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    criterion_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    maximum_rating: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="5")
    default_weight: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, server_default="1.000")
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    applicability_scope: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ALL")
    applicability_value: Mapped[str | None] = mapped_column(String(120))
    active_status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="ACTIVE")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)

    scorecard_criteria: Mapped[list[ScorecardCriteria]] = relationship(back_populates="criterion")


class Scorecard(Base):
    __tablename__ = "scorecards"
    __table_args__ = (
        UniqueConstraint("interview_id", "reviewer_id", "revision_no"),
        CheckConstraint("revision_no >= 1", name="revision_positive"),
        CheckConstraint(
            "recommendation IS NULL OR recommendation IN "
            "('STRONG_HIRE', 'HIRE_FURTHER_REVIEW', 'BORDERLINE', 'NO_HIRE')",
            name="recommendation",
        ),
        CheckConstraint("overall_score IS NULL OR overall_score BETWEEN 1 AND 5", name="overall_score"),
        CheckConstraint(
            "completion_status IN ('DRAFT', 'SUBMITTED', 'SUPERSEDED')",
            name="completion_status",
        ),
        CheckConstraint(
            "(completion_status = 'DRAFT' AND submitted_at IS NULL) OR "
            "(completion_status IN ('SUBMITTED', 'SUPERSEDED') AND submitted_at IS NOT NULL)",
            name="submitted_timestamp",
        ),
        Index("ix_scorecards_interview_status", "interview_id", "completion_status"),
        Index("ix_scorecards_reviewer_submitted", "reviewer_id", "submitted_at"),
        Index("ix_scorecards_supersedes_id", "supersedes_scorecard_id"),
    )

    scorecard_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    interview_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("interviews.interview_id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("interviewers.interviewer_id", ondelete="RESTRICT"), nullable=False
    )
    supersedes_scorecard_id: Mapped[str | None] = mapped_column(
        String(120), ForeignKey("scorecards.scorecard_id", ondelete="RESTRICT")
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    recommendation: Mapped[str | None] = mapped_column(String(24))
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    completion_status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="DRAFT")
    submitted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    interview: Mapped[Interview] = relationship(back_populates="scorecards")
    reviewer: Mapped[Interviewer] = relationship(back_populates="scorecards")
    criteria: Mapped[list[ScorecardCriteria]] = relationship(back_populates="scorecard")
    supersedes: Mapped[Scorecard | None] = relationship(
        remote_side="Scorecard.scorecard_id", back_populates="superseded_by"
    )
    superseded_by: Mapped[list[Scorecard]] = relationship(back_populates="supersedes")


class ScorecardCriteria(Base):
    __tablename__ = "scorecard_criteria"
    __table_args__ = (
        UniqueConstraint("scorecard_id", "criterion_id"),
        CheckConstraint("rating BETWEEN 1 AND maximum_rating_snapshot", name="rating_range"),
        CheckConstraint("weight_snapshot > 0", name="weight_positive"),
        CheckConstraint("maximum_rating_snapshot = 5", name="maximum_rating"),
        Index("ix_scorecard_criteria_criterion_id", "criterion_id"),
    )

    scorecard_criteria_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    scorecard_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("scorecards.scorecard_id", ondelete="RESTRICT"), nullable=False
    )
    criterion_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("evaluation_criteria.criterion_id", ondelete="RESTRICT"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comments: Mapped[str | None] = mapped_column(Text)
    criterion_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    weight_snapshot: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    maximum_rating_snapshot: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="5")
    mandatory_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    scorecard: Mapped[Scorecard] = relationship(back_populates="criteria")
    criterion: Mapped[EvaluationCriterion] = relationship(back_populates="scorecard_criteria")


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint("application_id", "offer_version"),
        CheckConstraint("offer_version >= 1", name="version_positive"),
        CheckConstraint("proposed_salary > 0", name="salary_positive"),
        CheckConstraint("band_min_snapshot > 0 AND band_min_snapshot <= band_max_snapshot", name="band_range"),
        CheckConstraint("compensation_period IN ('YEAR', 'MONTH', 'HOUR')", name="compensation_period"),
        CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'SENT', 'ACCEPTED', 'DECLINED', "
            "'RETURNED_FOR_REVISION', 'REJECTED', 'EXPIRED', 'WITHDRAWN')",
            name="status",
        ),
        CheckConstraint(
            "proposed_salary BETWEEN band_min_snapshot AND band_max_snapshot OR "
            "(exception_reason IS NOT NULL AND length(trim(exception_reason)) > 0)",
            name="exception_reason",
        ),
        CheckConstraint("expires_at IS NULL OR sent_at IS NULL OR expires_at > sent_at", name="expiry"),
        CheckConstraint(
            "(status NOT IN ('SENT', 'ACCEPTED', 'DECLINED', 'EXPIRED') OR sent_at IS NOT NULL)",
            name="sent_timestamp",
        ),
        CheckConstraint(
            "(status = 'ACCEPTED' AND accepted_at IS NOT NULL AND accepted_at >= sent_at) OR "
            "(status <> 'ACCEPTED' AND accepted_at IS NULL)",
            name="accepted_timestamp",
        ),
        CheckConstraint(
            "(status = 'DECLINED' AND declined_at IS NOT NULL AND declined_at >= sent_at) OR "
            "(status <> 'DECLINED' AND declined_at IS NULL)",
            name="declined_timestamp",
        ),
        Index("ix_offers_application_status", "application_id", "status"),
        Index("ix_offers_status_expiry", "status", "expires_at"),
        Index("ix_offers_supersedes_offer_id", "supersedes_offer_id"),
    )

    offer_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("applications.application_id", ondelete="RESTRICT"), nullable=False
    )
    supersedes_offer_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("offers.offer_id", ondelete="RESTRICT")
    )
    offer_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    proposed_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    band_min_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    band_max_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    compensation_period: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="DRAFT")
    exception_reason: Mapped[str | None] = mapped_column(Text)
    offer_date: Mapped[date | None] = mapped_column(Date)
    joining_date: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    accepted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    declined_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    application: Mapped[Application] = relationship(back_populates="offers")
    approvals: Mapped[list[Approval]] = relationship(back_populates="offer")
    supersedes: Mapped[Offer | None] = relationship(
        remote_side="Offer.offer_id", back_populates="superseded_by"
    )
    superseded_by: Mapped[list[Offer]] = relationship(back_populates="supersedes")


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("offer_id", "approval_sequence"),
        CheckConstraint("approval_sequence >= 1", name="approval_sequence_positive"),
        CheckConstraint("approval_type IN ('STANDARD', 'COMPENSATION_EXCEPTION')", name="approval_type"),
        CheckConstraint(
            "decision IN ('PENDING', 'APPROVED', 'REJECTED', 'RETURNED_FOR_REVISION')",
            name="decision",
        ),
        CheckConstraint(
            "(decision = 'PENDING' AND decided_at IS NULL) OR "
            "(decision <> 'PENDING' AND decided_at IS NOT NULL)",
            name="decision_timestamp",
        ),
        CheckConstraint(
            "decision NOT IN ('REJECTED', 'RETURNED_FOR_REVISION') OR "
            "(comments IS NOT NULL AND length(trim(comments)) > 0)",
            name="decision_comment_required",
        ),
        Index("ix_approvals_offer_decision", "offer_id", "decision"),
        Index("ix_approvals_approver_decided", "approver_id", "decided_at"),
    )

    approval_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    offer_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("offers.offer_id", ondelete="RESTRICT"), nullable=False
    )
    approval_sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    approval_stage: Mapped[str] = mapped_column(String(80), nullable=False)
    approval_type: Mapped[str] = mapped_column(String(28), nullable=False, server_default="STANDARD")
    approver_id: Mapped[str] = mapped_column(String(80), nullable=False)
    approver_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(80), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False, server_default="PENDING")
    comments: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    offer: Mapped[Offer] = relationship(back_populates="approvals")


class ApplicationStageHistory(Base):
    __tablename__ = "application_stage_history"
    __table_args__ = (
        UniqueConstraint("application_id", "history_sequence"),
        CheckConstraint("history_sequence >= 1", name="history_sequence_positive"),
        CheckConstraint(
            "previous_stage IS NULL OR previous_stage IN ('APPLIED', 'SCREENING', 'ASSESSMENT', "
            "'TECHNICAL_INTERVIEW', 'MANAGERIAL_INTERVIEW', 'HR_INTERVIEW', 'OFFER', 'HIRED', "
            "'REJECTED', 'WITHDRAWN')",
            name="previous_stage",
        ),
        CheckConstraint(
            "new_stage IN ('APPLIED', 'SCREENING', 'ASSESSMENT', 'TECHNICAL_INTERVIEW', "
            "'MANAGERIAL_INTERVIEW', 'HR_INTERVIEW', 'OFFER', 'HIRED', 'REJECTED', 'WITHDRAWN')",
            name="new_stage",
        ),
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN ('ACTIVE', 'ON_HOLD', 'CLOSED')",
            name="previous_status",
        ),
        CheckConstraint("new_status IN ('ACTIVE', 'ON_HOLD', 'CLOSED')", name="new_status"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_nonempty"),
    )

    stage_history_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("applications.application_id", ondelete="RESTRICT"), nullable=False
    )
    history_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_stage: Mapped[str | None] = mapped_column(String(32))
    new_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(12))
    new_status: Mapped[str] = mapped_column(String(12), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="stage_history")


class InterviewRescheduleHistory(Base):
    __tablename__ = "interview_reschedule_history"
    __table_args__ = (
        UniqueConstraint("interview_id", "reschedule_sequence"),
        CheckConstraint("reschedule_sequence >= 1", name="reschedule_sequence_positive"),
        CheckConstraint("previous_start_at < previous_end_at", name="previous_interval"),
        CheckConstraint("new_start_at < new_end_at", name="new_interval"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_nonempty"),
    )

    reschedule_history_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    interview_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("interviews.interview_id", ondelete="RESTRICT"), nullable=False
    )
    reschedule_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_start_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    previous_end_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    new_start_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    new_end_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    interview: Mapped[Interview] = relationship(back_populates="reschedule_history")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "(related_entity_type IS NULL AND related_entity_id IS NULL) OR "
            "(related_entity_type IS NOT NULL AND related_entity_id IS NOT NULL)",
            name="related_entity_pair",
        ),
        CheckConstraint(
            "actor_type IN ('USER', 'SYSTEM', 'SERVICE')",
            name="actor_type",
        ),
        CheckConstraint(
            "actor_type <> 'USER' OR (actor_id IS NOT NULL AND actor_name_snapshot IS NOT NULL)",
            name="user_actor_identity",
        ),
        Index("ix_audit_events_entity_time", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_events_related_time", "related_entity_type", "related_entity_id", "occurred_at"),
    )

    audit_event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    related_entity_type: Mapped[str | None] = mapped_column(String(40))
    related_entity_id: Mapped[str | None] = mapped_column(String(160))
    previous_state: Mapped[str | None] = mapped_column(Text)
    new_state: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="USER")
    actor_id: Mapped[str | None] = mapped_column(String(80))
    actor_name_snapshot: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
