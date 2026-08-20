"""Strict report and bounded evidence-context models."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paperpilot.domain import SourceLocator


class ReportPaperContext(BaseModel):
    """Verified structured analysis retained for one report source paper."""

    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    title: str | None = None
    research_problem: str
    method_name: str | None = None
    method_problem: str | None = None
    method_summary: str
    innovations: list[str]
    limitations: list[str]
    datasets: list[str]
    metrics: dict[str, str]
    baselines: list[str]
    findings: list[str]
    contributions: list[str]
    evidence_ids: list[UUID]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("title", "method_name", "method_problem")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("research_problem", "method_summary")
    @classmethod
    def validate_required_paper_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("report paper context text must not be empty")
        return value


class ReportEvidenceContext(BaseModel):
    """One accepted evidence item available to the report writer."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    paper_id: UUID
    quote: str
    normalized_fact: str
    locator: SourceLocator
    claim: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("quote", "normalized_fact", "claim")
    @classmethod
    def validate_evidence_text(cls, value: str) -> str:
        """Require nonempty evidence text."""

        value = value.strip()
        if not value:
            raise ValueError("report evidence text must not be empty")
        return value

    @model_validator(mode="after")
    def validate_locator_paper(self) -> "ReportEvidenceContext":
        if self.locator.paper_id != self.paper_id:
            raise ValueError("locator paper_id must match evidence paper_id")
        return self


class ReportContext(BaseModel):
    """Bounded, serialized collection of accepted evidence across papers."""

    model_config = ConfigDict(extra="forbid")

    paper_ids: list[UUID]
    papers: list[ReportPaperContext] = Field(default_factory=list)
    evidence: list[ReportEvidenceContext]
    context_text: str
    char_count: int = Field(ge=0)
    max_chars: int = Field(ge=1)
    total_available_evidence: int = Field(ge=0)
    truncated: bool
    warnings: list[str]

    @model_validator(mode="after")
    def validate_context_bounds(self) -> "ReportContext":
        if self.char_count != len(self.context_text):
            raise ValueError("char_count must equal context_text length")
        if self.char_count > self.max_chars:
            raise ValueError("report context exceeds max_chars")
        if any(item.paper_id not in self.paper_ids for item in self.evidence):
            raise ValueError("all evidence paper IDs must be retained in paper_ids")
        return self


class ReportClaim(BaseModel):
    """One explicit report claim and its supporting evidence references."""

    model_config = ConfigDict(extra="forbid")

    text: str
    evidence_ids: list[UUID]

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("report claim must not be empty")
        return value


class ReportSection(BaseModel):
    """A titled collection of claims and its declared evidence set."""

    model_config = ConfigDict(extra="forbid")

    title: str
    claims: list[ReportClaim]
    evidence_ids: list[UUID]

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("report section title must not be empty")
        return value


class ReportCitation(BaseModel):
    """A report citation bound to one exact accepted evidence quote."""

    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    paper_title: str | None = None
    evidence_id: UUID
    quote: str
    locator: SourceLocator

    @field_validator("quote")
    @classmethod
    def validate_quote(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("report citation quote must not be empty")
        return value

    @field_validator("paper_title")
    @classmethod
    def normalize_paper_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_locator_paper(self) -> "ReportCitation":
        if self.locator.paper_id != self.paper_id:
            raise ValueError("citation locator must reference citation paper_id")
        return self


class ResearchReport(BaseModel):
    """Final structured research report grounded in verified evidence."""

    model_config = ConfigDict(extra="forbid")

    question: str
    title: str
    summary: str
    sections: list[ReportSection]
    citations: list[ReportCitation]
    evidence_ids: list[UUID]
    warnings: list[str]

    @field_validator("question", "title", "summary")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("report text must not be empty")
        return value
