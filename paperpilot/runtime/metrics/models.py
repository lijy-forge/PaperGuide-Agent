"""Serializable production runtime metrics contracts."""

from pydantic import BaseModel, ConfigDict, Field


class RuntimeMetricsSnapshot(BaseModel):
    """JSON-safe cumulative counters and point-in-time runtime gauges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submitted_total: int = Field(ge=0)
    completed_total: int = Field(ge=0)
    failed_total: int = Field(ge=0)
    cancelled_total: int = Field(ge=0)
    dead_letter_total: int = Field(ge=0)
    active_workers: int = Field(ge=0)
    queue_size: int = Field(ge=0)
    running_tasks: int = Field(ge=0)
    lease_expired_total: int = Field(ge=0)
    stale_worker_rejected_total: int = Field(ge=0)
    average_execution_time_ms: float = Field(ge=0.0)
