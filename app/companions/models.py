from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Status = Literal["Pass", "Fail", "Partial", "Not verified", "Blocked", "Not applicable"]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checklist_id: str = Field(min_length=1, max_length=64)
    status: Status
    evidence_ids: list[str] = Field(max_length=100)
    observation: str = Field(max_length=8_000)
    reason: str = Field(min_length=1, max_length=8_000)
    missing_evidence: list[str] = Field(max_length=100)
    suggested_action: str = Field(max_length=8_000)
    requires_internal_review: bool


class CompanionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    review_id: str = Field(min_length=1, max_length=100)
    batch_id: str = Field(min_length=1, max_length=100)
    checklist_version: str = Field(min_length=1, max_length=32)
    summary: str = Field(max_length=12_000)
    findings: list[Finding] = Field(min_length=1, max_length=100)
    limitations: list[str] = Field(max_length=100)
    review_notice: str = Field(min_length=1, max_length=4_000)
