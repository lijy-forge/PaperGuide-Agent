"""Configuration thresholds for research workflow orchestration."""

from pydantic import BaseModel, ConfigDict, Field


class OrchestratorConfig(BaseModel):
    """Bounded retry and quality policy for a future research graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_retrieval_attempts: int = Field(default=2, ge=1)
    max_ingestion_attempts_per_paper: int = Field(default=2, ge=1)
    max_reader_attempts_per_paper: int = Field(default=2, ge=1)
    max_verifier_attempts_per_paper: int = Field(default=2, ge=1)
    max_paper_concurrency: int = Field(default=3, ge=1, le=3)
    minimum_verified_papers: int = Field(default=1, ge=0)
    minimum_verification_score: float = Field(default=0.7, ge=0.0, le=1.0)
    allow_degraded_completion: bool = True
    route_conflicts_to_human_review: bool = True
