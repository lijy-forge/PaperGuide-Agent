"""Author domain model."""

from pydantic import BaseModel, ConfigDict, field_validator


class Author(BaseModel):
    """An author and the affiliations reported by paper metadata."""

    model_config = ConfigDict(extra="forbid")

    full_name: str
    normalized_name: str | None = None
    affiliations: list[str]

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("full_name must not be empty")
        return value
