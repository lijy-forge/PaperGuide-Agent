"""Deterministic offline timing projection from persisted progress events."""

from pydantic import BaseModel, ConfigDict, Field

from paperguide.runtime.host.models import TaskEvent

from .models import ProgressStage


class ProgressTimingSummary(BaseModel):
    """Stage durations calculated from start/completion event pairs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_ms: float = Field(ge=0.0)
    stage_ms: dict[ProgressStage, float] = Field(default_factory=dict)


def summarize_progress_timing(events: list[TaskEvent]) -> ProgressTimingSummary:
    """Return stable stage timings without writing derived values back to SQLite."""

    started: dict[ProgressStage, object] = {}
    durations: dict[ProgressStage, float] = {}
    for event in sorted(events, key=lambda item: item.event_id):
        payload = event.progress
        if payload is None:
            continue
        if event.event_type.value.endswith("_started"):
            started[payload.stage] = event.created_at
        elif event.event_type.value.endswith("_completed") and payload.stage in started:
            durations[payload.stage] = max(0.0, (event.created_at - started[payload.stage]).total_seconds() * 1000)  # type: ignore[operator]
    return ProgressTimingSummary(total_ms=sum(durations.values()), stage_ms=durations)
