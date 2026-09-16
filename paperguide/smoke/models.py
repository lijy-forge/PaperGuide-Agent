"""Safe, serializable diagnostics for real PaperGuide smoke runs."""

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SmokeStage(str, Enum):
    """Ordered observable stages in one end-to-end research run."""

    RUNTIME_CONFIGURATION = "runtime_configuration"
    PROVIDER_INITIALIZATION = "provider_initialization"
    PAPER_RETRIEVAL = "paper_retrieval"
    METADATA_NORMALIZATION = "metadata_normalization"
    PDF_DOWNLOAD = "pdf_download"
    PDF_PARSE = "pdf_parse"
    PAPER_READING = "paper_reading"
    EVIDENCE_MAPPING = "evidence_mapping"
    EVIDENCE_VERIFICATION = "evidence_verification"
    REPORT_GENERATION = "report_generation"
    ARTIFACT_EXPORT = "artifact_export"


class SmokeStageStatus(str, Enum):
    """Lifecycle status of one safe smoke diagnostic stage."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class SmokeTestStatus(str, Enum):
    """Overall outcome of one smoke run."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageDiagnostic(BaseModel):
    """Content-free timing and safe failure information for one stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: SmokeStage
    status: SmokeStageStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0.0)
    safe_error_code: str | None = None
    safe_message: str | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> "StageDiagnostic":
        for value in (self.started_at, self.completed_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("stage timestamps must be timezone-aware")
        if self.status in (SmokeStageStatus.SUCCEEDED, SmokeStageStatus.FAILED):
            if self.started_at is None or self.completed_at is None:
                raise ValueError("completed stage requires both timestamps")
        if self.status is SmokeStageStatus.FAILED and not self.safe_error_code:
            raise ValueError("failed stage requires a safe error code")
        if self.status is not SmokeStageStatus.FAILED and self.safe_error_code:
            raise ValueError("only failed stage may contain an error code")
        return self


class SmokeTestResult(BaseModel):
    """Safe summary written to ``smoke-result.json`` after a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID = Field(default_factory=uuid4)
    question_fingerprint: str
    status: SmokeTestStatus
    stages: list[StageDiagnostic]
    retrieved_papers: int = Field(ge=0)
    downloaded_documents: int = Field(ge=0)
    parsed_documents: int = Field(ge=0)
    verified_claims: int = Field(ge=0)
    rejected_claims: int = Field(ge=0)
    report_generated: bool
    artifact_filename: str | None = None
    duration_ms: float = Field(ge=0.0)
    warnings: list[str]

    @field_validator("question_fingerprint")
    @classmethod
    def validate_fingerprint(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if len(normalized) != 64 or any(
            char not in "0123456789abcdef" for char in normalized
        ):
            raise ValueError("question_fingerprint must be SHA-256 hex")
        return normalized

    @field_validator("artifact_filename")
    @classmethod
    def validate_artifact_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip() or "/" in value or "\\" in value:
            raise ValueError("artifact_filename must be a basename")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> "SmokeTestResult":
        if self.status is SmokeTestStatus.PASSED:
            if not self.report_generated or self.artifact_filename is None:
                raise ValueError("passed smoke run requires a report artifact")
            if any(stage.status is SmokeStageStatus.FAILED for stage in self.stages):
                raise ValueError("passed smoke run cannot contain a failed stage")
        return self


def utc_now() -> datetime:
    """Return an aware UTC timestamp for diagnostic recording."""

    return datetime.now(UTC)
