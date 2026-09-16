"""Serializable checkpoint records for research orchestration state."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paperguide.orchestration.state import ResearchState


class CheckpointRecord(BaseModel):
    """A versioned snapshot of one research run's orchestration state."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    state: ResearchState
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_timestamps(self) -> "CheckpointRecord":
        """Require timezone-aware timestamps in chronological order."""

        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("checkpoint timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self
