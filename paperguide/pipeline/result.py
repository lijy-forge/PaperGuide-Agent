"""Result models returned by PaperGuide search pipelines."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from paperguide.domain import PaperCandidate

NonNegativeInt = Annotated[int, Field(ge=0)]


class SearchResult(BaseModel):
    """Aggregated papers, per-source diagnostics, and result counts."""

    model_config = ConfigDict(extra="forbid")

    papers: list[PaperCandidate]
    source_results: dict[str, NonNegativeInt]
    source_errors: dict[str, str]
    warnings: list[str]
    total_found: NonNegativeInt
    total_after_dedup: NonNegativeInt
