"""Structured health-check contracts for the PaperPilot runtime."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class HealthStatus(str, Enum):
    """Overall or component-level runtime health state."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class HealthCheckResult(BaseModel):
    """Result of one isolated runtime prerequisite check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: HealthStatus
    message: str


class HealthReport(BaseModel):
    """Serializable readiness report for the PaperPilot process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: HealthStatus
    ready: bool
    checks: list[HealthCheckResult]
