"""TaskExecutor-compatible client for a live persistent local TaskHost."""

from uuid import UUID, uuid4

from paperguide.application import (
    ResearchRequest,
    ResearchTask,
    ResearchTaskStatus,
)
from paperguide.execution import PersistentTaskStore, TaskHandle

from .broker import SQLiteHostBroker
from .exceptions import TaskHostUnavailableError
from .models import TaskEventType


class PersistentTaskHostClient:
    """Submit and query tasks through SQLite while requiring a live host."""

    def __init__(
        self,
        task_store: PersistentTaskStore,
        broker: SQLiteHostBroker,
    ) -> None:
        self.task_store = task_store
        self.broker = broker

    def submit(self, request: ResearchRequest) -> TaskHandle:
        self._require_host()
        safe_request = ResearchRequest.model_validate(request.model_dump())
        created = self.task_store.save(
            ResearchTask(
                run_id=uuid4(),
                question=safe_request.question,
                status=ResearchTaskStatus.CREATED,
            )
        )
        self.broker.record_event(
            created.task_id,
            TaskEventType.TASK_CREATED,
            ResearchTaskStatus.CREATED,
        )
        queued = self.task_store.update(
            created.task_id,
            status=ResearchTaskStatus.QUEUED,
        )
        try:
            self.broker.enqueue(queued.task_id, safe_request)
            self.broker.record_event(
                queued.task_id,
                TaskEventType.TASK_QUEUED,
                ResearchTaskStatus.QUEUED,
            )
        except Exception as error:
            self.task_store.update(
                queued.task_id,
                status=ResearchTaskStatus.FAILED,
                artifact=None,
                error=f"task submission failed ({type(error).__name__})",
            )
            raise
        return TaskHandle(
            task_id=queued.task_id,
            status=ResearchTaskStatus.QUEUED,
            created_at=queued.created_at,
        )

    def get_status(self, task_id: UUID) -> ResearchTask:
        self._require_host()
        return self.task_store.get(task_id)

    def list_tasks(
        self,
        *,
        limit: int,
        offset: int = 0,
        status: ResearchTaskStatus | None = None,
    ) -> tuple[list[ResearchTask], int]:
        """Return one page of tasks, newest first, with the matching total.

        Unlike submission this does not require a live host: reading history is
        exactly what is wanted when the host is down, and refusing it would
        hide the tasks whose fate the operator is trying to find out.
        """

        return self.task_store.list_page(
            limit=limit,
            offset=offset,
            status=status.value if status is not None else None,
        )

    def cancel(self, task_id: UUID) -> ResearchTask:
        self._require_host()
        task = self.task_store.get(task_id)
        if task.status is ResearchTaskStatus.QUEUED:
            cancelled = self.task_store.update(
                task_id,
                status=ResearchTaskStatus.CANCELLED,
                artifact=None,
                error=None,
            )
            self.broker.mark_done(
                task_id,
                event_type=TaskEventType.TASK_CANCELLED,
                status=ResearchTaskStatus.CANCELLED,
            )
            return cancelled
        if task.status is ResearchTaskStatus.RUNNING:
            return self.task_store.update(
                task_id,
                status=ResearchTaskStatus.CANCEL_REQUESTED,
                artifact=None,
                error=None,
            )
        return task

    def _require_host(self) -> None:
        if not self.broker.host_available():
            raise TaskHostUnavailableError(
                "persistent task host is unavailable; run 'paperguide server start'"
            )
