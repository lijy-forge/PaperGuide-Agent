"""Task storage protocol and isolated process-local implementation."""

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol, runtime_checkable
from uuid import UUID

from .exceptions import TaskNotFoundError
from .models import ResearchTask


@runtime_checkable
class TaskStoreProtocol(Protocol):
    """Storage-independent lifecycle operations for research tasks."""

    def save(self, task: ResearchTask) -> ResearchTask:
        """Save and return an isolated task copy."""

        ...

    def get(self, task_id: UUID) -> ResearchTask:
        """Load an isolated task copy."""

        ...

    def update(self, task_id: UUID, **changes: object) -> ResearchTask:
        """Validate and replace selected mutable task fields."""

        ...

    def delete(self, task_id: UUID) -> bool:
        """Delete a task and report whether it existed."""

        ...

    def list(self) -> list[ResearchTask]:
        """List isolated task snapshots in stable creation order."""

        ...


class InMemoryTaskStore:
    """Thread-safe in-memory task store with deep-copy isolation."""

    _UPDATABLE_FIELDS = {"status", "artifact", "error", "report_quality_status"}

    def __init__(self) -> None:
        self._tasks: dict[str, ResearchTask] = {}
        self._lock = RLock()

    def save(self, task: ResearchTask) -> ResearchTask:
        """Store a validated deep copy by task ID."""

        stored = ResearchTask.model_validate(task.model_dump())
        with self._lock:
            self._tasks[str(task.task_id)] = deepcopy(stored)
        return deepcopy(stored)

    def get(self, task_id: UUID) -> ResearchTask:
        """Return a deep copy or raise TaskNotFoundError."""

        with self._lock:
            task = self._tasks.get(str(task_id))
            if task is None:
                raise TaskNotFoundError(f"research task not found: {task_id}")
            return deepcopy(task)

    def update(self, task_id: UUID, **changes: object) -> ResearchTask:
        """Update lifecycle fields and refresh updated_at."""

        unknown = set(changes) - self._UPDATABLE_FIELDS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"task fields cannot be updated: {names}")
        with self._lock:
            current = self._tasks.get(str(task_id))
            if current is None:
                raise TaskNotFoundError(f"research task not found: {task_id}")
            payload = current.model_dump()
            payload.update(changes)
            payload["updated_at"] = datetime.now(timezone.utc)
            updated = ResearchTask.model_validate(payload)
            self._tasks[str(task_id)] = deepcopy(updated)
            return deepcopy(updated)

    def delete(self, task_id: UUID) -> bool:
        """Delete a task without failing when it is absent."""

        with self._lock:
            return self._tasks.pop(str(task_id), None) is not None

    def list(self) -> list[ResearchTask]:
        """Return deep copies in stable insertion order."""

        with self._lock:
            return [deepcopy(task) for task in self._tasks.values()]
