"""Serializable task submission contracts for background execution."""

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paperguide.application import ResearchTaskStatus


class TaskHandle(BaseModel):
    """Immediate immutable acknowledgement returned for a queued research task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    status: ResearchTaskStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_handle(self) -> "TaskHandle":
        if self.created_at.tzinfo is None:
            raise ValueError("task handle created_at must be timezone-aware")
        if self.status not in (
            ResearchTaskStatus.CREATED,
            ResearchTaskStatus.QUEUED,
        ):
            raise ValueError("task handle must represent a submitted task")
        return self
