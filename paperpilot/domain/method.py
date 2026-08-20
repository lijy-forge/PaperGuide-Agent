"""Method analysis domain model."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MethodSummary(BaseModel):
    """A concise, evidence-backed summary of a paper's method."""

    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    name: str | None = None
    problem: str | None = None
    summary: str
    innovations: list[str]
    limitations: list[str]
    evidence_ids: list[UUID]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("summary must not be empty")
        return value
