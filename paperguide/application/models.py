"""Strict request, task, and result contracts for the application layer."""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paperguide.export import ArtifactMetadata, ExportFormat, ExportResult
from paperguide.domain import ManualPaperSource
from paperguide.reporting import ResearchReport, SurveyReport


class ResearchRequest(BaseModel):
    """Validated user request for one complete PaperGuide research run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str
    # Publicly this is the maximum number of final CORE papers. Until the
    # metadata relevance gate exists, the legacy pipeline keeps its conservative
    # downstream limit for compatibility and cost control.
    max_papers: int = Field(default=10, ge=1, le=50)
    export_format: ExportFormat = ExportFormat.MARKDOWN
    manual_sources: list[ManualPaperSource] = Field(default_factory=list, max_length=20)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("research question must not be empty")
        return value


class ResearchTaskStatus(str, Enum):
    """Application-visible lifecycle states for a research task."""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    HUMAN_REVIEW = "human_review"


class ReportQualityStatus(str, Enum):
    """Quality outcome, deliberately separate from execution status."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ResearchTask(BaseModel):
    """Persistable task status and optional exported artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    question: str
    status: ResearchTaskStatus = ResearchTaskStatus.CREATED
    report_quality_status: ReportQualityStatus = ReportQualityStatus.PENDING
    artifact: ArtifactMetadata | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("task question must not be empty")
        return value

    @field_validator("error")
    @classmethod
    def validate_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("task error must not be empty")
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "ResearchTask":
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("task timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        if self.status is ResearchTaskStatus.COMPLETED and self.artifact is None:
            raise ValueError("completed task must contain artifact metadata")
        if (
            self.status is not ResearchTaskStatus.COMPLETED
            and self.artifact is not None
        ):
            raise ValueError("only completed task may contain artifact metadata")
        error_statuses = {
            ResearchTaskStatus.FAILED,
            ResearchTaskStatus.DEAD_LETTER,
        }
        if self.status in error_statuses and self.error is None:
            raise ValueError("failed task must contain an error")
        if self.status not in error_statuses and self.error is not None:
            raise ValueError("only failed task may contain an error")
        return self


class ResearchResult(BaseModel):
    """Application result containing task, report, and export outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: ResearchTask
    report: ResearchReport | SurveyReport | None = None
    export_result: ExportResult | None = None

    @model_validator(mode="after")
    def validate_result_state(self) -> "ResearchResult":
        if self.task.status is ResearchTaskStatus.COMPLETED:
            if self.report is None or self.export_result is None:
                raise ValueError("completed result requires report and export result")
        return self
