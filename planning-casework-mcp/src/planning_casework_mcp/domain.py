"""Domain model for planning casework at Harrowfield District Council (an invented council)."""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

REF_PATTERN = re.compile(r"^\d{2}/\d{5}/(HOU|FUL|LBC|COU|PA|ADV)$")


class AppType(StrEnum):
    HOUSEHOLDER = "HOU"
    FULL = "FUL"
    LISTED_BUILDING = "LBC"
    CHANGE_OF_USE = "COU"
    PRIOR_APPROVAL = "PA"
    ADVERTISEMENT = "ADV"


class Status(StrEnum):
    RECEIVED = "received"  # not yet valid: the clock has not started
    CONSULTATION = "consultation"
    ASSESSMENT = "assessment"
    APPROVED = "approved"
    REFUSED = "refused"
    WITHDRAWN = "withdrawn"

    @property
    def is_open(self) -> bool:
        return self in {Status.RECEIVED, Status.CONSULTATION, Status.ASSESSMENT}


class Stance(StrEnum):
    OBJECT = "object"
    SUPPORT = "support"
    NEUTRAL = "neutral"


class Recommendation(StrEnum):
    APPROVE = "approve"
    REFUSE = "refuse"


class Application(BaseModel):
    ref: str
    app_type: AppType
    is_major: bool = False
    is_eia: bool = False
    description: str
    address: str
    ward: str
    applicant: str
    applicant_is_member_or_staff: bool = False
    councillor_call_in: bool = False
    received: date
    validated: date | None = None
    consultation_start: date | None = None
    extension_agreed_to: date | None = None
    status: Status
    case_officer: str

    @field_validator("ref")
    @classmethod
    def _ref_format(cls, v: str) -> str:
        if not REF_PATTERN.match(v):
            raise ValueError(f"bad application reference {v!r}")
        return v


class Constraint(BaseModel):
    kind: str  # conservation_area, listed_building, flood_zone, tpo, article_4
    detail: str


class ConsulteeResponse(BaseModel):
    consultee: str
    response: str  # no_objection, conditions, objection, pending
    summary: str


class PublicComment(BaseModel):
    comment_id: int
    address: str
    stance: Stance
    text: str
    received: date


class Policy(BaseModel):
    policy_id: str
    title: str
    text: str


class DecisionDraft(BaseModel):
    draft_id: int
    ref: str
    recommendation: Recommendation
    reasons: list[str]
    conditions: list[str]
    route: str
    approved_by: str
    created_at: str
    idempotency_key: str


class DraftRequest(BaseModel):
    """Validated input for drafting a decision notice."""

    ref: str
    recommendation: Recommendation
    reasons: list[str] = Field(default_factory=list, max_length=12)
    conditions: list[str] = Field(default_factory=list, max_length=30)
    idempotency_key: str = Field(min_length=6, max_length=64)
    approved_by: str = Field(min_length=2, max_length=80)

    @field_validator("ref")
    @classmethod
    def _ref_format(cls, v: str) -> str:
        if not REF_PATTERN.match(v):
            raise ValueError(f"bad application reference {v!r}")
        return v
