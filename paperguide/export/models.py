"""Serializable contracts for report export results."""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExportFormat(str, Enum):
    """Supported deterministic report export formats."""

    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"


class ArtifactMetadata(BaseModel):
    """Immutable-identifying metadata for one generated export artifact."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    format: ExportFormat
    file_path: str
    size_bytes: int = Field(ge=0)
    sha256: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    execution_id: str | None = None
    task_id: UUID | None = None

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("artifact file_path must not be empty")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("artifact sha256 must be a 64-character hex digest")
        return normalized

    @model_validator(mode="after")
    def validate_created_at(self) -> "ArtifactMetadata":
        if self.created_at.tzinfo is None:
            raise ValueError("artifact created_at must be timezone-aware")
        if (self.execution_id is None) != (self.task_id is None):
            raise ValueError(
                "artifact execution_id and task_id must be provided together"
            )
        if (
            self.execution_id is not None
            and not self.execution_id.startswith(f"{self.task_id}:")
        ):
            raise ValueError("artifact execution_id must belong to task_id")
        return self


class ExportResult(BaseModel):
    """Rendered text or generated file metadata for one export operation."""

    model_config = ConfigDict(extra="forbid")

    format: ExportFormat
    media_type: str
    content: str | None = None
    file_path: str | None = None
    size_bytes: int = Field(ge=0)
    warnings: list[str]
    artifact: ArtifactMetadata | None = None

    @model_validator(mode="after")
    def validate_payload_location(self) -> "ExportResult":
        if not self.media_type.strip():
            raise ValueError("export media_type must not be empty")
        if self.content is None and self.file_path is None:
            raise ValueError("export must contain content or a file path")
        if self.format is ExportFormat.PDF and self.file_path is None:
            raise ValueError("PDF export must contain a file path")
        if self.artifact is not None:
            if self.artifact.format is not self.format:
                raise ValueError("artifact format must match export format")
            if self.artifact.file_path != self.file_path:
                raise ValueError("artifact file_path must match export file_path")
            if self.artifact.size_bytes != self.size_bytes:
                raise ValueError("artifact size must match export size")
        return self
