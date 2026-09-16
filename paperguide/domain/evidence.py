"""Evidence and source-location domain models."""

from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import EvidenceType


class SourceLocator(BaseModel):
    """A stable location for evidence inside a parsed paper."""

    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    section_title: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    paragraph_index: int | None = Field(default=None, ge=0)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "SourceLocator":
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must be greater than or equal to page_start")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must be greater than or equal to char_start")
        return self


class Evidence(BaseModel):
    """A normalized fact linked to an exact location in a paper."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    paper_id: UUID
    evidence_type: EvidenceType
    quote: str
    normalized_fact: str
    locator: SourceLocator
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("quote", "normalized_fact")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence text must not be empty")
        return value

    @model_validator(mode="after")
    def validate_paper_reference(self) -> "Evidence":
        if self.locator.paper_id != self.paper_id:
            raise ValueError("locator.paper_id must match evidence.paper_id")
        return self
