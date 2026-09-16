"""Paper discovery domain model."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .author import Author
from .enums import FullTextStatus, PaperSource


class PaperCandidate(BaseModel):
    """A normalized paper returned by one or more discovery sources."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    title: str
    normalized_title: str
    abstract: str | None = None
    authors: list[Author]
    publication_year: int | None = Field(default=None, ge=1)
    published_at: datetime | None = None
    updated_at: datetime | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    semantic_scholar_id: str | None = None
    openalex_id: str | None = None
    sources: list[PaperSource]
    landing_page_url: str | None = None
    pdf_url: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    full_text_status: FullTextStatus
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    selection_reason: str | None = None

    @field_validator("title", "normalized_title")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("paper titles must not be empty")
        return value
