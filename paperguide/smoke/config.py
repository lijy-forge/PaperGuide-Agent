"""Cost-bounded configuration for manually enabled real smoke runs."""

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paperguide.domain import PaperSource
from paperguide.export import ExportFormat


class SmokeTestConfig(BaseModel):
    """Validated one-shot configuration that defaults to one arXiv paper."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = "What methods combine YOLO with visual SLAM?"
    sources: list[PaperSource] = Field(default_factory=lambda: [PaperSource.ARXIV])
    max_papers: int = Field(default=1, ge=1, le=3)
    export_format: ExportFormat = ExportFormat.MARKDOWN
    timeout_seconds: float = Field(default=300.0, gt=0.0, le=1800.0)
    require_verified_evidence: bool = True
    output_directory: Path = Path("runtime-data/smoke")

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("smoke question must not be empty")
        if len(normalized) > 4000:
            raise ValueError("smoke question exceeds API limit")
        return normalized

    @model_validator(mode="after")
    def validate_sources(self) -> "SmokeTestConfig":
        # OpenAlex belongs here for the same reason it was added to the
        # default retrievers: it needs no key and covers journals. Leaving it
        # out meant the one switch for a real run could only use the two
        # sources that rate-limit, so the run failed for reasons that had
        # nothing to do with the pipeline being tested.
        allowed = {
            PaperSource.ARXIV,
            PaperSource.OPENALEX,
            PaperSource.SEMANTIC_SCHOLAR,
        }
        if not self.sources or any(source not in allowed for source in self.sources):
            raise ValueError(
                "smoke sources must be arXiv, OpenAlex or Semantic Scholar"
            )
        if len(self.sources) != len(set(self.sources)):
            raise ValueError("smoke sources must not contain duplicates")
        return self


def real_e2e_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Require an explicit opt-in before any real network or LLM execution."""

    source = os.environ if environ is None else environ
    return source.get("PAPERGUIDE_RUN_REAL_E2E", "").strip() == "1"
