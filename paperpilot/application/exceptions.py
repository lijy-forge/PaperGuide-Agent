"""Exceptions raised by the PaperPilot application service layer."""

from uuid import UUID


class ApplicationError(RuntimeError):
    """Base exception for application-layer failures."""


class TaskNotFoundError(ApplicationError):
    """Raised when an application task does not exist."""


class ResearchExecutionError(ApplicationError):
    """Raised when graph, reporting, or export execution fails."""

    def __init__(
        self,
        message: str,
        *,
        task_id: UUID,
        run_id: UUID,
    ) -> None:
        super().__init__(message)
        self.task_id = task_id
        self.run_id = run_id
