"""Structured metadata, lease, and event contracts for the persistent TaskHost."""

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paperpilot.application import ResearchRequest, ResearchTaskStatus
from paperpilot.progress.events import TaskEventType


class HostStatus(str, Enum):
    """Lifecycle states of one persistent runtime host process."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class LeaseLossReason(str, Enum):
    """Reasons a worker may no longer publish execution results."""

    EXPIRED = "expired"
    HOST_OWNERSHIP_LOST = "host_ownership_lost"
    FENCING_TOKEN_CHANGED = "fencing_token_changed"
    TASK_UNAVAILABLE = "task_unavailable"


class RuntimeHostMetadata(BaseModel):
    """Serializable identity and liveness metadata for the active host."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host_id: UUID
    pid: int = Field(ge=1)
    version: str
    started_at: datetime
    heartbeat: datetime
    status: HostStatus

    @model_validator(mode="after")
    def validate_timestamps(self) -> "RuntimeHostMetadata":
        if self.started_at.tzinfo is None or self.heartbeat.tzinfo is None:
            raise ValueError("host timestamps must be timezone-aware")
        if self.heartbeat < self.started_at:
            raise ValueError("host heartbeat cannot precede started_at")
        if not self.version.strip():
            raise ValueError("host version must not be empty")
        return self


class TaskLease(BaseModel):
    """One atomically acquired task request lease."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    request: ResearchRequest
    lease_owner: UUID
    lease_until: datetime
    attempt_count: int = Field(ge=1)
    fencing_token: int = Field(ge=1)
    execution_id: str

    @model_validator(mode="after")
    def validate_lease_until(self) -> "TaskLease":
        if self.lease_until.tzinfo is None:
            raise ValueError("lease_until must be timezone-aware")
        expected = f"{self.task_id}:{self.attempt_count}"
        if self.execution_id != expected:
            raise ValueError("execution_id must match task_id and attempt_count")
        return self


class RuntimeMetrics(BaseModel):
    """Point-in-time counters for persistent runtime coordination."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submitted: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    active_workers: int = Field(ge=0)
    queue_size: int = Field(ge=0)
    running_tasks: int = Field(default=0, ge=0)
    dead_letter_total: int = Field(default=0, ge=0)
    lease_expired_total: int = Field(default=0, ge=0)
    stale_worker_rejected_total: int = Field(default=0, ge=0)
    average_execution_time_ms: float = Field(default=0.0, ge=0.0)


class LeaseRenewalResult(BaseModel):
    """Result of validating and renewing one fenced worker lease."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    renewed: bool
    lease_until: datetime | None = None
    loss_reason: LeaseLossReason | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "LeaseRenewalResult":
        if self.renewed == (self.loss_reason is not None):
            raise ValueError("lease renewal outcome is inconsistent")
        if self.renewed and self.lease_until is None:
            raise ValueError("renewed lease requires lease_until")
        return self


class DeadLetterTask(BaseModel):
    """Content-free record of one task exhausted by runtime failures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    execution_id: str
    last_status: str
    last_error_type: str
    failed_stage: str
    attempt_count: int = Field(ge=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_dead_letter(self) -> "DeadLetterTask":
        if self.created_at.tzinfo is None:
            raise ValueError("dead letter created_at must be timezone-aware")
        for value in (
            self.execution_id,
            self.last_status,
            self.last_error_type,
            self.failed_stage,
        ):
            if not value.strip():
                raise ValueError("dead letter text fields must not be empty")
        return self


class RuntimeRecoveryResult(BaseModel):
    """Deterministic result of one idempotent startup recovery pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    retained: list[UUID]
    requeued: list[UUID]
    dead_lettered: list[UUID]


class TaskEvent(BaseModel):
    """Content-free audit record for one task lifecycle transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: int = Field(ge=1)
    task_id: UUID
    event_type: TaskEventType
    host_id: UUID | None
    status: ResearchTaskStatus
    attempt_count: int = Field(default=0, ge=0)
    duration_ms: float | None = Field(default=None, ge=0.0)
    progress: "ProgressEventPayload | None" = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_created_at(self) -> "TaskEvent":
        if self.created_at.tzinfo is None:
            raise ValueError("task event created_at must be timezone-aware")
        return self


from paperpilot.progress.models import ProgressEventPayload  # noqa: E402
