"""Deterministic dead-letter and runtime recovery services."""

import logging
import re
from threading import Event, Thread
from typing import Protocol
from uuid import UUID

from paperpilot.application import (
    ResearchTask,
    ResearchTaskStatus,
    TaskStoreProtocol,
)

from .broker import SQLiteHostBroker
from .models import DeadLetterTask, RuntimeRecoveryResult, TaskLease

_ERROR_TYPE = re.compile(r"\(([A-Za-z_][A-Za-z0-9_.]*)\)\s*$")
_TERMINAL_STATUSES = {
    ResearchTaskStatus.COMPLETED,
    ResearchTaskStatus.FAILED,
    ResearchTaskStatus.HUMAN_REVIEW,
    ResearchTaskStatus.CANCELLED,
    ResearchTaskStatus.DEAD_LETTER,
}
LOGGER = logging.getLogger("paperpilot.runtime.host.recovery")


class DeadLetterServiceProtocol(Protocol):
    """Move exhausted executions and query safe dead-letter records."""

    def move_failed(
        self,
        task: ResearchTask,
        lease: TaskLease,
        *,
        host_id: UUID,
        failed_stage: str = "execution",
    ) -> bool:
        """Move one currently fenced failure to DEAD_LETTER."""

        ...

    def list_dead_letters(self) -> list[DeadLetterTask]:
        """Return safe dead-letter records."""

        ...


class RuntimeRecoveryProtocol(Protocol):
    """Recover persistent runtime state after host startup or lease loss."""

    def recover(self) -> RuntimeRecoveryResult:
        """Run one idempotent recovery pass."""

        ...


class RuntimeReconcilerProtocol(Protocol):
    """Lifecycle boundary for periodic stale-task reconciliation."""

    def start(self) -> None:
        """Start the independent reconciliation loop."""

        ...

    def stop(self) -> None:
        """Stop the reconciliation loop and wait for its helper thread."""

        ...


class DeadLetterService:
    """Coordinate fenced queue finalization with application task state."""

    def __init__(
        self,
        broker: SQLiteHostBroker,
        task_store: TaskStoreProtocol,
    ) -> None:
        self.broker = broker
        self.task_store = task_store

    def move_failed(
        self,
        task: ResearchTask,
        lease: TaskLease,
        *,
        host_id: UUID,
        failed_stage: str = "execution",
    ) -> bool:
        if task.status is not ResearchTaskStatus.FAILED:
            raise ValueError("only failed tasks may enter dead letter")
        changed = self.broker.move_to_dead_letter(
            task.task_id,
            execution_id=lease.execution_id,
            last_status=task.status.value,
            last_error_type=self._safe_error_type(task.error),
            failed_stage=failed_stage,
            attempt_count=lease.attempt_count,
            fencing_token=lease.fencing_token,
            host_id=host_id,
        )
        if changed:
            self.task_store.update(
                task.task_id,
                status=ResearchTaskStatus.DEAD_LETTER,
                artifact=None,
                error="retry limit exceeded (RetryLimitExceeded)",
            )
        return changed

    def list_dead_letters(self) -> list[DeadLetterTask]:
        return self.broker.list_dead_letters()

    @staticmethod
    def _safe_error_type(error: str | None) -> str:
        if error is None:
            return "ExecutionError"
        match = _ERROR_TYPE.search(error)
        return match.group(1) if match is not None else "ExecutionError"


class RuntimeRecoveryService:
    """Apply broker recovery decisions to the persisted application task view."""

    def __init__(
        self,
        broker: SQLiteHostBroker,
        task_store: TaskStoreProtocol,
        *,
        max_attempts: int,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self.broker = broker
        self.task_store = task_store
        self.max_attempts = max_attempts

    def recover(self) -> RuntimeRecoveryResult:
        result = self.broker.recover_incomplete(
            max_attempts=self.max_attempts,
        )
        for task_id in result.requeued:
            task = self.task_store.get(task_id)
            if task.status not in _TERMINAL_STATUSES:
                self.task_store.update(
                    task_id,
                    status=ResearchTaskStatus.QUEUED,
                    artifact=None,
                    error=None,
                )
        for task_id in result.dead_lettered:
            task = self.task_store.get(task_id)
            if task.status is not ResearchTaskStatus.DEAD_LETTER:
                self.task_store.update(
                    task_id,
                    status=ResearchTaskStatus.DEAD_LETTER,
                    artifact=None,
                    error="retry limit exceeded (RetryLimitExceeded)",
                )
        return result


class RuntimeReconciler:
    """Periodically run recovery independently of task execution dispatch."""

    def __init__(
        self,
        recovery_service: RuntimeRecoveryProtocol,
        *,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.recovery_service = recovery_service
        self.interval_seconds = interval_seconds
        self._stop_event = Event()
        self._thread: Thread | None = None
        self.last_error_type: str | None = None

    @property
    def is_running(self) -> bool:
        """Return whether the helper thread is currently alive."""

        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start one daemon reconciliation thread, idempotently."""

        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            name="paperpilot-runtime-reconciler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Request shutdown without leaving a non-daemon helper behind."""

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 2))

    def reconcile_once(self) -> RuntimeRecoveryResult:
        """Run one deterministic recovery pass through the existing service."""

        return self.recovery_service.recover()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.reconcile_once()
                self.last_error_type = None
            except Exception as error:
                # A transient store failure must not terminate future passes.
                self.last_error_type = type(error).__name__
                LOGGER.warning(
                    "runtime reconciliation pass failed (%s)",
                    self.last_error_type,
                )
            if self._stop_event.wait(self.interval_seconds):
                return
