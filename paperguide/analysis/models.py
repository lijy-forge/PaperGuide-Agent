"""Pydantic contracts for structured single-paper analysis."""

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paperguide.domain import Evidence, ExperimentSummary, MethodSummary


class EvidenceReference(BaseModel):
    """Raw evidence citation returned by a structured LLM."""

    model_config = ConfigDict(extra="forbid")

    evidence_key: str
    quote: str
    page_number: int | None = Field(default=None, ge=1)
    section_title: str | None = None
    claim: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("evidence_key", "quote", "claim")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence reference text must not be empty")
        return value


class MethodAnalysis(BaseModel):
    """LLM contract for a paper's method and claimed innovations."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    problem: str
    summary: str
    architecture: list[str]
    innovations: list[str]
    limitations: list[str]
    evidence_keys: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("problem", "summary")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("method analysis text must not be empty")
        return value


class ExperimentMetricAnalysis(BaseModel):
    """One reported metric and its optional comparison context."""

    model_config = ConfigDict(extra="forbid")

    dataset: str | None = None
    metric: str
    value: str | None = None
    baseline: str | None = None
    comparison: str | None = None
    evidence_keys: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("metric must not be empty")
        return value


class ExperimentAnalysis(BaseModel):
    """LLM contract for experiments, results, and reproducibility details."""

    model_config = ConfigDict(extra="forbid")

    objective: str | None = None
    datasets: list[str]
    baselines: list[str]
    metrics: list[ExperimentMetricAnalysis]
    findings: list[str]
    reproducibility_notes: list[str]
    evidence_keys: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class PaperReaderOutput(BaseModel):
    """Strict structured response required from the Paper Reader LLM."""

    model_config = ConfigDict(extra="forbid")

    research_problem: str
    contributions: list[str]
    method: MethodAnalysis
    experiments: ExperimentAnalysis
    limitations: list[str]
    evidence: list[EvidenceReference]
    analysis_warnings: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("research_problem")
    @classmethod
    def validate_research_problem(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("research_problem must not be empty")
        return value


class PaperContext(BaseModel):
    """Bounded, location-marked context supplied to the analysis LLM."""

    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    paper_id: UUID
    title: str
    selected_sections: list[str]
    page_ranges: list[tuple[int, int]]
    context_text: str
    token_estimate: int = Field(ge=0)
    truncated: bool
    warnings: list[str]


class EvidenceMappingResult(BaseModel):
    """Verified evidence, key mapping, and rejected-reference diagnostics."""

    model_config = ConfigDict(extra="forbid")

    evidence: list[Evidence]
    key_to_id: dict[str, UUID]
    warnings: list[str]
    rejected_keys: list[str]


class PaperAnalysisResult(BaseModel):
    """Validated, evidence-linked analysis for one parsed paper."""

    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    document_id: UUID
    paper_title: str | None = None
    research_problem: str
    contributions: list[str]
    method_summary: MethodSummary
    experiment_summary: ExperimentSummary
    evidence: list[Evidence]
    limitations: list[str]
    warnings: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    model_name: str | None = None
    prompt_version: str
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("research_problem", "prompt_version")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("analysis result text must not be empty")
        return value

    @field_validator("paper_title")
    @classmethod
    def normalize_paper_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_paper_and_evidence_references(self) -> "PaperAnalysisResult":
        if self.method_summary.paper_id != self.paper_id:
            raise ValueError("method_summary paper_id must match result paper_id")
        if self.experiment_summary.paper_id != self.paper_id:
            raise ValueError("experiment_summary paper_id must match result paper_id")
        if any(item.paper_id != self.paper_id for item in self.evidence):
            raise ValueError("all evidence must reference the result paper_id")

        evidence_ids = {item.id for item in self.evidence}
        referenced_ids = {
            *self.method_summary.evidence_ids,
            *self.experiment_summary.evidence_ids,
        }
        if not referenced_ids.issubset(evidence_ids):
            raise ValueError("summary evidence_ids must reference included evidence")
        return self
