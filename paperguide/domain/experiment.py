"""Experiment analysis domain model."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExperimentSummary(BaseModel):
    """Structured datasets, metrics, baselines, and findings for a paper."""

    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    datasets: list[str]
    metrics: dict[str, str]
    baselines: list[str]
    findings: list[str]
    evidence_ids: list[UUID]
    confidence: float = Field(ge=0.0, le=1.0)
