"""Public, intentionally narrow HTTP request and response contracts."""

from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paperpilot.application import ResearchTaskStatus
from paperpilot.export import ExportFormat
from paperpilot.runtime.host import TaskEventType
from paperpilot.progress.models import ProgressEventPayload


class APISettings(BaseModel):
    """Non-secret local demonstration API configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    title: str = "PaperPilot API"
    version: str = "10.17"
    api_prefix: str = "/api/v1"
    artifact_root: Path = Path("paperpilot-exports")
    cors_allowed_origins: list[str] = Field(default_factory=list)
    max_question_length: int = Field(default=4000, ge=1, le=20_000)
    max_event_page_size: int = Field(default=100, ge=20, le=1000)
    expose_error_details: bool = False

    @field_validator("title", "version")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("API text settings must not be empty")
        return value

    @field_validator("api_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith("/") or ".." in value:
            raise ValueError("api_prefix must be an absolute controlled path")
        return value

    @field_validator("artifact_root", mode="before")
    @classmethod
    def validate_artifact_root(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("artifact_root must not be empty")
        return value

    @model_validator(mode="after")
    def validate_cors(self) -> "APISettings":
        if any(not origin.strip() for origin in self.cors_allowed_origins):
            raise ValueError("CORS origins must not be empty")
        return self


class CreateResearchRequest(BaseModel):
    """Public request to enqueue one research task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str
    max_papers: int = Field(default=10, ge=1, le=50)
    export_format: ExportFormat = ExportFormat.MARKDOWN

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        return value


class TaskAcceptedResponse(BaseModel):
    """Minimal acknowledgement returned without waiting for execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    status: ResearchTaskStatus
    created_at: datetime


class TaskStatusResponse(BaseModel):
    """Sanitized task status without question, error text, or local paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    run_id: UUID
    status: ResearchTaskStatus
    created_at: datetime
    updated_at: datetime
    artifact_available: bool
    artifact_format: ExportFormat | None
    human_review_required: bool
    retryable: bool
    error_code: str | None


class TaskEventResponse(BaseModel):
    """Content-free public representation of a runtime task event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: int
    event_type: TaskEventType
    status: ResearchTaskStatus
    attempt_count: int
    duration_ms: float | None
    created_at: datetime
    progress: ProgressEventPayload | None = None


class MetricsResponse(BaseModel):
    """Public JSON runtime metrics response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submitted_total: int
    completed_total: int
    failed_total: int
    cancelled_total: int
    dead_letter_total: int
    active_workers: int
    queue_size: int
    running_tasks: int
    lease_expired_total: int
    stale_worker_rejected_total: int
    average_execution_time_ms: float


class HealthCheckResponse(BaseModel):
    """One sanitized API readiness check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    healthy: bool


class HealthResponse(BaseModel):
    """Liveness or readiness response without paths or process metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    status: str
    ready: bool
    checks: list[HealthCheckResponse]


class ErrorResponse(BaseModel):
    """Stable safe error envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    request_id: UUID
