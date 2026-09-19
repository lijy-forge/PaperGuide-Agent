"""User-supplied literature metadata and controlled PDF upload reference."""

from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import PaperSource


class ManualPaperSource(BaseModel):
    """A paper the user obtained themselves, supplied with an uploaded PDF.

    ``source`` records where they got it. It may not name a source the system
    searches automatically: a record claiming to come from arXiv, OpenAlex or
    Semantic Scholar would be indistinguishable from one the pipeline actually
    retrieved, and provenance is the point of recording it at all. Anything
    else is allowed — a paywalled IEEE or Springer paper is exactly the case
    manual upload exists for, and ``user_upload`` covers a publisher the
    enumeration does not name.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: PaperSource
    title: str
    source_url: str
    upload_id: UUID
    authors: list[str] = Field(default_factory=list, max_length=100)
    publication_year: int | None = Field(default=None, ge=1, le=3000)
    abstract: str | None = Field(default=None, max_length=20_000)
    doi: str | None = Field(default=None, max_length=512)

    AUTOMATIC_SOURCES: ClassVar[frozenset[PaperSource]] = frozenset(
        {
            PaperSource.ARXIV,
            PaperSource.CROSSREF,
            PaperSource.OPENALEX,
            PaperSource.SEMANTIC_SCHOLAR,
        }
    )

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: PaperSource) -> PaperSource:
        if value in ManualPaperSource.AUTOMATIC_SOURCES:
            names = ", ".join(sorted(item.value for item in ManualPaperSource.AUTOMATIC_SOURCES))
            raise ValueError(
                f"manual source must not claim an automatically searched source ({names})"
            )
        return value

    @field_validator("title", "source_url")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("manual source text must not be empty")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        if not value.casefold().startswith("https://") or len(value) > 2048:
            raise ValueError("manual source URL must be a valid HTTPS URL")
        return value

    @field_validator("authors")
    @classmethod
    def validate_authors(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        return list(dict.fromkeys(cleaned))

    @field_validator("abstract", "doi")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None