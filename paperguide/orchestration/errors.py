"""Safe structured errors for research orchestration state."""

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import PaperStageStatus, ResearchStep

MAX_ERROR_MESSAGE_LENGTH = 500
_AUTHORIZATION_HEADER_RE = re.compile(
    r"(?im)\bauthorization\s*:\s*[^\r\n]*"
)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|authorization|token)\b\s*[:=]\s*"
    r"(?:bearer\s+)?[^\s,;]+"
)
_BEARER_SECRET_RE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_SENSITIVE_TERM_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|authorization|bearer|token)\b"
)
_WHITESPACE_RE = re.compile(r"\s+")


class StateValidationError(ValueError):
    """Raised when a ResearchState violates its cross-field contract."""


def sanitize_message(message: str) -> str:
    """Redact credential terms, remove newlines, and bound an error message."""

    value = _AUTHORIZATION_HEADER_RE.sub("[REDACTED]", str(message))
    value = value.replace("\r", " ").replace("\n", " ")
    value = _ASSIGNMENT_SECRET_RE.sub("[REDACTED]", value)
    value = _BEARER_SECRET_RE.sub("[REDACTED]", value)
    value = _SENSITIVE_TERM_RE.sub("[REDACTED]", value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value[:MAX_ERROR_MESSAGE_LENGTH]


class ResearchError(BaseModel):
    """Sanitized error associated with a workflow stage and optional paper."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    stage: ResearchStep
    paper_id: UUID | None = None
    error_type: str
    message: str
    recoverable: bool
    attempt: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("message", mode="before")
    @classmethod
    def sanitize_error_message(cls, value: object) -> str:
        return sanitize_message(str(value))

    @field_validator("error_type", "message")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("error text must not be empty")
        return value


class PaperStageRecord(BaseModel):
    """Current per-paper workflow status and its most recent error."""

    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    status: PaperStageStatus
    attempt: int = Field(default=0, ge=0)
    last_error: ResearchError | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_last_error_paper(self) -> "PaperStageRecord":
        if (
            self.last_error is not None
            and self.last_error.paper_id is not None
            and self.last_error.paper_id != self.paper_id
        ):
            raise ValueError("last_error paper_id must match the stage record")
        return self
