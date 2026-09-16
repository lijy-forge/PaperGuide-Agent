"""Research configuration domain model."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import PaperSource
from .manual_source import ManualPaperSource


class ResearchConfig(BaseModel):
    """User-defined scope and limits for a PaperGuide research task."""

    model_config = ConfigDict(extra="forbid")

    question: str
    start_year: int | None = Field(default=None, ge=1)
    end_year: int | None = Field(default=None, ge=1)
    """Maximum final CORE-paper budget (legacy retriever limits remain bounded)."""

    max_papers: int = Field(default=10, ge=1, le=50)
    sources: list[PaperSource]
    open_access_only: bool = True
    language: str = "zh-CN"
    manual_sources: list[ManualPaperSource] = Field(default_factory=list, max_length=20)

    @field_validator("question", "language")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value

    @model_validator(mode="after")
    def validate_year_range(self) -> "ResearchConfig":
        if (
            self.start_year is not None
            and self.end_year is not None
            and self.end_year < self.start_year
        ):
            raise ValueError("end_year must be greater than or equal to start_year")
        return self
