"""Storage- and backend-neutral task executor protocol."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from paperguide.application import ResearchRequest, ResearchTask

from .models import TaskHandle


@runtime_checkable
class TaskExecutorProtocol(Protocol):
    """Submit research requests and query their externally visible status."""

    def submit(self, request: ResearchRequest) -> TaskHandle:
        """Queue one request and immediately return its task handle."""

        ...

    def get_status(self, task_id: UUID) -> ResearchTask:
        """Return an isolated task status snapshot."""

        ...

    def cancel(self, task_id: UUID) -> ResearchTask:
        """Cancel queued work or record a cooperative cancellation request."""

        ...
