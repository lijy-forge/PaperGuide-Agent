"""Safe, persisted, user-facing research progress telemetry."""

from .models import ProgressAppendMetrics, ProgressEventPayload, ProgressStage
from .events import TaskEventType
from .diagnostics import (
    FAILURE_CATEGORIES,
    sanitize_reader_exception,
    summarize_reader_diagnostics,
)

__all__ = [
    "ProgressEventPayload",
    "ProgressAppendMetrics",
    "ProgressStage",
    "TaskEventType",
    "FAILURE_CATEGORIES",
    "sanitize_reader_exception",
    "summarize_reader_diagnostics",
]
