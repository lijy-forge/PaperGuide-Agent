"""Typed failures for background task submission and execution control."""


class TaskExecutionError(RuntimeError):
    """Base exception for the task execution runtime."""


class TaskSubmissionError(TaskExecutionError):
    """Raised when a request cannot be queued for background execution."""
