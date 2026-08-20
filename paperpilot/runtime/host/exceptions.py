"""Typed errors for the persistent local task host boundary."""


class TaskHostError(RuntimeError):
    """Base exception for persistent task host operations."""


class TaskHostUnavailableError(TaskHostError):
    """Raised when no live task host heartbeat can be found."""


class TaskHostAlreadyRunningError(TaskHostError):
    """Raised when another live host owns the runtime database."""


class SchemaMigrationError(TaskHostError):
    """Raised when the runtime schema cannot be safely upgraded."""
