"""User-supplied literature metadata and controlled PDF upload reference."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import PaperSource


class ManualPaperSource(BaseModel):
    """A Google Scholar or CNKI record supplemented with an uploaded PDF."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: PaperSource
    title: str
    source_url: str
    upload_id: UUID
    authors: list[str] = Field(default_factory=list, max_length=100)
    publication_year: int | None = Field(default=None, ge=1, le=3000)
    abstract: str | None = Field(default=None, max_length=20_000)
    doi: str | None = Field(default=None, max_length=512)

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: PaperSource) -> PaperSource:
        if value not in {PaperSource.GOOGLE_SCHOLAR, PaperSource.CNKI}:
            raise ValueError("manual source must be google_scholar or cnki")
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