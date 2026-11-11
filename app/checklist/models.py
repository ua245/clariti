from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CaptureRecipe = Literal[
    "manual_text",
    "manual_screenshot",
    "static_page",
    "rendered_page",
    "authorized_internal_evidence",
]


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    category: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=500)
    evidence_needed: list[str] = Field(min_length=1, max_length=10)
    externally_verifiable: bool
    assessment_criteria: list[str] = Field(min_length=1, max_length=10)
    candidate_url_keywords: list[str] = Field(max_length=10)
    capture_recipe: CaptureRecipe


class ChecklistTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){1,2}$")
    items: list[ChecklistItem] = Field(min_length=1, max_length=100)
