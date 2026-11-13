from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RequisitionStatus = Literal[
    "DRAFT", "PENDING_APPROVAL", "OPEN", "ON_HOLD", "FILLED", "CLOSED", "CANCELLED"
]
ApplicationStage = Literal[
    "APPLIED", "SCREENING", "ASSESSMENT", "TECHNICAL_INTERVIEW",
    "MANAGERIAL_INTERVIEW", "HR_INTERVIEW", "OFFER", "HIRED", "REJECTED", "WITHDRAWN",
]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HiringManagerCreate(APIModel):
    employee_code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    department: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("employee_code")
    @classmethod
    def normalize_employee_code(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("Employee code must not be blank.")
        return normalized

    @field_validator("name", "department")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field must not be blank.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_manager_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("A valid email address is required.")
        return normalized

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class HiringManagerRead(BaseModel):
    hiring_manager_id: str
    employee_code: str
    name: str
    email: str
    department: str
    phone: str | None
    active_status: Literal["ACTIVE", "INACTIVE"]
    created_at: datetime
    updated_at: datetime


class RequisitionCreate(APIModel):
    hiring_manager_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    department: str = Field(min_length=1, max_length=100)
    job_family: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=160)
    employment_type: Literal["FULL_TIME", "PART_TIME", "CONTRACT", "TEMPORARY", "INTERN"]
    work_mode: Literal["ONSITE", "HYBRID", "REMOTE"]
    headcount: int = Field(default=1, gt=0, le=1000)
    min_salary: Decimal | None = Field(default=None, ge=0)
    max_salary: Decimal | None = Field(default=None, gt=0)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    compensation_period: Literal["YEAR", "MONTH", "HOUR"] | None = None
    opening_date: date
    closing_date: date | None = None

    @field_validator(
        "hiring_manager_id", "title", "department", "job_family", "location",
        mode="before",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("This field must not be blank.")
        return value.strip()

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @model_validator(mode="after")
    def validate_requisition(self) -> RequisitionCreate:
        if self.min_salary is not None and self.max_salary is not None:
            if self.min_salary > self.max_salary:
                raise ValueError("min_salary must not exceed max_salary.")
        if self.closing_date is not None and self.closing_date < self.opening_date:
            raise ValueError("closing_date must be on or after opening_date.")
        return self


class RequisitionUpdate(APIModel):
    reason: str = Field(min_length=1, max_length=2000)
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    department: str | None = Field(default=None, min_length=1, max_length=100)
    job_family: str | None = Field(default=None, min_length=1, max_length=100)
    location: str | None = Field(default=None, min_length=1, max_length=160)
    employment_type: Literal["FULL_TIME", "PART_TIME", "CONTRACT", "TEMPORARY", "INTERN"] | None = None
    work_mode: Literal["ONSITE", "HYBRID", "REMOTE"] | None = None
    headcount: int | None = Field(default=None, gt=0, le=1000)
    min_salary: Decimal | None = Field(default=None, ge=0)
    max_salary: Decimal | None = Field(default=None, gt=0)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    compensation_period: Literal["YEAR", "MONTH", "HOUR"] | None = None
    opening_date: date | None = None
    closing_date: date | None = None

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("An update reason is required.")
        return value.strip()

    @field_validator("title", "department", "job_family", "location", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("This field must not be blank.")
        return value.strip()

    @model_validator(mode="after")
    def validate_salary_range(self) -> RequisitionUpdate:
        if (
            self.min_salary is not None
            and self.max_salary is not None
            and self.min_salary > self.max_salary
        ):
            raise ValueError("min_salary must not exceed max_salary.")
        if (
            self.opening_date is not None
            and self.closing_date is not None
            and self.closing_date < self.opening_date
        ):
            raise ValueError("closing_date must be on or after opening_date.")
        return self


class RequisitionRead(BaseModel):
    requisition_id: str
    hiring_manager_id: str
    hiring_manager_name: str
    title: str
    description: str | None
    department: str
    job_family: str
    location: str
    employment_type: str
    work_mode: str
    headcount: int
    status: RequisitionStatus
    approval_status: str
    min_salary: Decimal | None
    max_salary: Decimal | None
    currency_code: str | None
    compensation_period: str | None
    opening_date: date
    closing_date: date | None
    created_at: datetime
    updated_at: datetime


class RequisitionApprovalAssignment(APIModel):
    approval_stage: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$")
    approval_sequence: int = Field(ge=1, le=10)
    approver_id: str = Field(min_length=1, max_length=80)


class RequisitionApprovalSubmission(APIModel):
    approvals: list[RequisitionApprovalAssignment] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def require_submission_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A submission reason is required.")
        return normalized

    @model_validator(mode="after")
    def validate_approval_chain(self) -> RequisitionApprovalSubmission:
        sequences = [item.approval_sequence for item in self.approvals]
        stages = [item.approval_stage for item in self.approvals]
        approvers = [item.approver_id for item in self.approvals]
        if len(set(sequences)) != len(sequences):
            raise ValueError("Approval sequence numbers must be unique.")
        if sorted(sequences) != list(range(1, len(sequences) + 1)):
            raise ValueError("Approval sequence numbers must start at 1 and be contiguous.")
        if len(set(stages)) != len(stages):
            raise ValueError("Approval stages must be unique.")
        if len(set(approvers)) != len(approvers):
            raise ValueError("Each approval stage must have a different approver.")
        return self


class RequisitionApprovalDecision(APIModel):
    decision: Literal["APPROVED", "REJECTED", "RETURNED_FOR_REVISION"]
    comments: str | None = Field(default=None, max_length=2000)

    @field_validator("comments")
    @classmethod
    def normalize_decision_comments(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RequisitionLifecycleReason(APIModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def require_lifecycle_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A lifecycle reason is required.")
        return normalized


class CandidateCreate(APIModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    location: str | None = Field(default=None, max_length=160)
    education_level: Literal["SECONDARY", "ASSOCIATE", "BACHELOR", "MASTER", "DOCTORATE", "OTHER"] | None = None
    education_summary: str | None = Field(default=None, max_length=500)
    total_experience_months: int = Field(default=0, ge=0, le=1200)
    skills: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def strip_candidate_name(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Candidate names must not be blank.")
        return value.strip()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("A valid email address is required.")
        return email

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))
        if any(len(value) > 100 for value in normalized):
            raise ValueError("Skill names must be at most 100 characters.")
        return normalized


class PublicApplicationCreate(APIModel):
    requisition_id: str = Field(min_length=1, max_length=80)
    candidate: CandidateCreate
    privacy_consent: bool

    @field_validator("privacy_consent")
    @classmethod
    def require_privacy_consent(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Consent is required to submit an application.")
        return value


class CandidateRead(BaseModel):
    candidate_id: str
    first_name: str
    last_name: str
    email: str
    phone: str | None
    location: str | None
    education_level: str | None
    education_summary: str | None
    total_experience_months: int
    skills: list[str]
    created_at: datetime


class ApplicationCreate(APIModel):
    candidate_id: str = Field(min_length=1, max_length=80)
    requisition_id: str = Field(min_length=1, max_length=80)
    source_channel: Literal["CAREER_SITE", "REFERRAL", "JOB_BOARD", "AGENCY", "DIRECT", "OTHER"] = "DIRECT"
    source_detail: str | None = Field(default=None, max_length=200)


class ApplicationTransition(APIModel):
    new_stage: ApplicationStage | None = None
    new_status: Literal["ACTIVE", "ON_HOLD", "CLOSED"] | None = None
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A transition reason is required.")
        return value.strip()


class ApplicationRead(BaseModel):
    application_id: str
    candidate_id: str
    candidate_name: str
    candidate_email: str
    requisition_id: str
    requisition_title: str
    current_stage: ApplicationStage
    status: str
    source_channel: str
    applied_at: datetime
    updated_at: datetime
