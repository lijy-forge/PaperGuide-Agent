"""Pydantic models for downloaded and parsed paper documents."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Page(BaseModel):
    """Text extracted from one 1-based PDF page."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    text: str


class Section(BaseModel):
    """A heuristically detected paper section spanning one or more pages."""

    model_config = ConfigDict(extra="forbid")

    title: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    text: str

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("section title must not be empty")
        return value

    @model_validator(mode="after")
    def validate_page_range(self) -> "Section":
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class Document(BaseModel):
    """Parsed paper text with stable page and section boundaries."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    paper_id: UUID
    title: str
    source_path: str
    pages: list[Page]
    sections: list[Section]
    metadata: dict[str, Any]

    @field_validator("title", "source_path")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value


class DownloadedPDF(BaseModel):
    """A validated PDF file downloaded for a specific paper."""

    model_config = ConfigDict(extra="forbid")

    file_path: str
    paper_id: UUID
    size_bytes: int = Field(gt=0)

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("file_path must not be empty")
        return value
