"""Public, content-free progress payload contracts."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProgressStage(str, Enum):
    """Stable user-facing stages for a literature research task."""

    QUERY_PLANNING = "query_planning"
    RETRIEVAL = "retrieval"
    METADATA_FILTERING = "metadata_filtering"
    PDF_PROCESSING = "pdf_processing"
    PAPER_READING = "paper_reading"
    EVIDENCE_VERIFICATION = "evidence_verification"
    FINAL_RELEVANCE = "final_relevance"
    SURVEY_SYNTHESIS = "survey_synthesis"
    ARTIFACT_EXPORT = "artifact_export"


class ProgressEventPayload(BaseModel):
    """Validated public counters and a short paper-title preview only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: ProgressStage
    completed: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    succeeded: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    skipped: int | None = Field(default=None, ge=0)
    paper_title_preview: str | None = None
    elapsed_ms: float | None = Field(default=None, ge=0.0)
    message: str | None = Field(default=None, max_length=160)

    @field_validator("paper_title_preview", "message")
    @classmethod
    def normalize_public_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if value:
            # This is the only content-bearing public field. Keep it useful
            # without ever persisting an unbounded paper title.
            return value[:100]
        return value or None

    @model_validator(mode="after")
    def validate_counts(self) -> "ProgressEventPayload":
        if (self.completed is None) != (self.total is None):
            raise ValueError("completed and total must be supplied together")
        if self.completed is not None and self.completed > self.total:  # type: ignore[operator]
            raise ValueError("completed cannot exceed total")
        counters = (self.succeeded, self.failed, self.skipped)
        if any(value is not None for value in counters):
            if any(value is None for value in counters) or self.completed is None:
                raise ValueError("progress counters require completed and total")
            if self.completed != sum(counters):
                raise ValueError("completed must equal succeeded + failed + skipped")
        return self


class ProgressAppendMetrics(BaseModel):
    """Local process metrics for best-effort SQLite progress appends."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(default=0, ge=0)
    mean_latency_ms: float = Field(default=0.0, ge=0.0)
    p95_latency_ms: float = Field(default=0.0, ge=0.0)
