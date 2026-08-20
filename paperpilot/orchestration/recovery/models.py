"""Serializable contracts for deterministic recovery decisions."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paperpilot.orchestration.enums import ResearchStep
from paperpilot.orchestration.state import ResearchState


class RecoveryAction(str, Enum):
    """Actions available to a caller after inspecting a checkpoint."""

    RESUME = "resume"
    RETRY = "retry"
    COMPLETE = "complete"
    COMPLETE_DEGRADED = "complete_degraded"
    HUMAN_REVIEW = "human_review"
    ABORT = "abort"


class RecoveryDecision(BaseModel):
    """A validated recovery outcome containing an isolated state snapshot."""

    model_config = ConfigDict(extra="forbid")

    action: RecoveryAction
    reason: str
    state: ResearchState
    failed_stage: ResearchStep | None = None
    retry_stage: str | None = None
    remaining_attempts: int = Field(ge=0)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        """Require a nonempty human-readable recovery reason."""

        value = value.strip()
        if not value:
            raise ValueError("recovery reason must not be empty")
        return value

    @field_validator("retry_stage")
    @classmethod
    def validate_retry_stage(cls, value: str | None) -> str | None:
        """Reject an explicitly supplied empty retry stage."""

        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("retry_stage must not be empty")
        return value
