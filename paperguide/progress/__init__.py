"""Safe, persisted, user-facing research progress telemetry."""

from .diagnostics import (
    FAILURE_CATEGORIES,
    sanitize_reader_exception,
    summarize_reader_diagnostics,
)
from .events import TaskEventType
from .models import ProgressAppendMetrics, ProgressEventPayload, ProgressStage

__all__ = [
    "ProgressEventPayload",
    "ProgressAppendMetrics",
    "ProgressStage",
    "TaskEventType",
    "FAILURE_CATEGORIES",
    "sanitize_reader_exception",
    "summarize_reader_diagnostics",
]
