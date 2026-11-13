from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from src.schemas.recruitment_schema import APIModel

RoleCode = Literal["ADMIN", "RECRUITER", "HIRING_MANAGER", "INTERVIEWER", "APPROVER"]
ScopeType = Literal["GLOBAL", "DEPARTMENT", "REQUISITION", "RESOURCE"]


class RoleGrantCreate(APIModel):
    role_code: RoleCode
    scope_type: ScopeType
    scope_department: str | None = Field(default=None, max_length=100)
    scope_requisition_id: str | None = Field(default=None, max_length=80)


class StaffAccountCreate(APIModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    hiring_manager_id: str | None = Field(default=None, max_length=80)
    interviewer_id: str | None = Field(default=None, max_length=80)
    role_grants: list[RoleGrantCreate] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def reject_conflicting_profile_links(self) -> StaffAccountCreate:
        if self.hiring_manager_id and self.interviewer_id:
            raise ValueError("A staff account may link to only one profile type.")
        return self


class UserRoleGrantRead(APIModel):
    role_code: str
    scope_type: str
    scope_department: str | None
    scope_requisition_id: str | None


class StaffAccountRead(APIModel):
    user_id: str
    email: str
    display_name: str
    status: str
    hiring_manager_id: str | None
    interviewer_id: str | None
    role_grants: list[UserRoleGrantRead]


class RoleRead(APIModel):
    role_id: UUID
    role_code: str
    name: str
    description: str
