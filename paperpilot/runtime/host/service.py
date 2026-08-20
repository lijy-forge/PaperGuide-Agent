"""Long-lived dispatcher connecting persistent requests to the existing executor."""

import logging
import inspect
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

from paperpilot.application import ResearchTaskStatus
from paperpilot.bootstrap import ApplicationContainer, create_application
from paperpilot.execution import InMemoryTaskExecutor, PersistentTaskStore

from paperpilot.runtime.settings import RuntimeSettings

from .broker import SQLiteHostBroker
from .hardening import (
    DeadLetterService,
    RuntimeReconciler,
    RuntimeRecoveryService,
)
from .lease import WorkerLeaseMonitor
from .models import HostStatus, TaskEventType, TaskLease
from .preflight import HostProviderPreflight
from paperpilot.progress.publisher import ProgressPublisher

ApplicationFactory = Callable[..., ApplicationContainer]

_TERMINAL_STATUSES = {
    ResearchTaskStatus.COMPLETED,
    ResearchTaskStatus.FAILED,
    ResearchTaskStatus.HUMAN_REVIEW,
    ResearchTaskStatus.CANCELLED,
    ResearchTaskStatus.DEAD_LETTER,
}
_TERMINAL_EVENTS = {
    ResearchTaskStatus.COMPLETED: TaskEventType.TASK_COMPLETED,
    ResearchTaskStatus.FAILED: TaskEventType.TASK_FAILED,
    ResearchTaskStatus.CANCELLED: TaskEventType.TASK_CANCELLED,
}
LOGGER = logging.getLogger("paperpilot.runtime.host")
HOST_VERSION = "paperpilot-10.16"


class TaskHost:
    """Own application dependencies and dispatch persistent tasks until shutdown."""

    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        database_path: str | Path | None = None,
        application_factory: ApplicationFactory = create_application,
        poll_interval: float = 0.1,
        heartbeat_ttl: float = 5.0,
        lease_seconds: float = 30.0,
        max_attempts: int = 3,
        reconciliation_interval: float | None = None,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if reconciliation_interval is not None and reconciliation_interval <= 0:
            raise ValueError("reconciliation_interval must be positive")
        self.settings = RuntimeSettings.model_validate(settings.model_dump())
        self.database_path = Path(
            database_path or self.settings.task_database_path()
        )
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.host_id = uuid4()
        self.started_at = datetime.now(timezone.utc)
        self.task_store = PersistentTaskStore(self.database_path)
        self.broker = SQLiteHostBroker(
            self.database_path,
            heartbeat_ttl=heartbeat_ttl,
        )
        self.progress_publisher = ProgressPublisher(self.broker)
        factory_parameters = inspect.signature(application_factory).parameters
        factory_kwargs = {"task_store": self.task_store}
        if "progress_publisher" in factory_parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in factory_parameters.values()
        ):
            factory_kwargs["progress_publisher"] = self.progress_publisher
        self.container = application_factory(
            self.settings.to_bootstrap_config(), **factory_kwargs
        )
        self.executor = InMemoryTaskExecutor(
            self.container.application_service,
            self.task_store,
        )
        self.dead_letter_service = DeadLetterService(
            self.broker,
            self.task_store,
        )
        self.recovery_service = RuntimeRecoveryService(
            self.broker,
            self.task_store,
            max_attempts=self.max_attempts,
        )
        self.reconciler = RuntimeReconciler(
            self.recovery_service,
            interval_seconds=(
                reconciliation_interval
                if reconciliation_interval is not None
                else self.lease_seconds / 3
            ),
        )
        self._stop_event = Event()
        self._task_started: dict[UUID, float] = {}
        self._task_attempts: dict[UUID, int] = {}
        self._task_fences: dict[UUID, tuple[int, str]] = {}
        self._task_leases: dict[UUID, TaskLease] = {}
        self._lease_monitors: dict[UUID, WorkerLeaseMonitor] = {}

    def serve_forever(self) -> None:
        """Acquire host ownership and dispatch requests until shutdown."""

        self.broker.acquire_host(
            self.host_id,
            version=HOST_VERSION,
            started_at=self.started_at,
        )
        LOGGER.info(
            "task host acquired",
            extra={"host_id": str(self.host_id), "status": HostStatus.STARTING.value},
        )
        failed = False
        try:
            self.broker.heartbeat(self.host_id, status=HostStatus.RUNNING)
            self.reconciler.start()
            while not self._stop_event.is_set():
                self.broker.heartbeat(
                    self.host_id,
                    status=HostStatus.RUNNING,
                )
                self._process_provider_preflight()
                self._finalize_dispatched()
                lease = self.broker.claim_next(
                    self.host_id,
                    lease_seconds=self.lease_seconds,
                    require_healthy_host=True,
                )
                if lease is not None:
                    self._dispatch(lease)
                self._stop_event.wait(self.poll_interval)
        except Exception:
            failed = True
            self.broker.set_host_status(self.host_id, HostStatus.FAILED)
            LOGGER.error(
                "task host failed",
                extra={"host_id": str(self.host_id), "status": HostStatus.FAILED.value},
            )
            raise
        finally:
            self.reconciler.stop()
            if not failed:
                self.broker.set_host_status(self.host_id, HostStatus.STOPPING)
            self.executor.shutdown()
            self._finalize_dispatched()
            self._stop_lease_monitors()
            self.broker.release_host(
                self.host_id,
                status=HostStatus.FAILED if failed else HostStatus.STOPPED,
            )
            LOGGER.info(
                "task host stopped",
                extra={
                    "host_id": str(self.host_id),
                    "status": (
                        HostStatus.FAILED.value
                        if failed
                        else HostStatus.STOPPED.value
                    ),
                },
            )

    def shutdown(self) -> None:
        """Request cooperative host shutdown."""

        self._stop_event.set()

    def _process_provider_preflight(self) -> None:
        """Execute at most one explicit provider probe in this Host process."""

        request_id = self.broker.claim_provider_preflight(self.host_id)
        if request_id is None:
            return
        probe = HostProviderPreflight(
            self.container.structured_llm,
            provider=self.settings.llm_provider,
            model=self.settings.model_name,
        )
        result = probe.run()
        self.broker.complete_provider_preflight(request_id, result)
        LOGGER.info(
            "provider preflight completed",
            extra={
                "stage": "provider_preflight",
                "status": result.status.value,
                "failure_category": result.failure_category.value,
            },
        )

    def _dispatch(self, lease: TaskLease) -> None:
        task_id = lease.task_id
        task = self.task_store.get(task_id)
        if task.status is ResearchTaskStatus.CANCELLED:
            self.broker.mark_done(
                task_id,
                event_type=TaskEventType.TASK_CANCELLED,
                host_id=self.host_id,
                status=ResearchTaskStatus.CANCELLED,
                attempt_count=lease.attempt_count,
                fencing_token=lease.fencing_token,
                execution_id=lease.execution_id,
            )
            return
        if task.status is ResearchTaskStatus.CANCEL_REQUESTED:
            self.task_store.update(
                task_id,
                status=ResearchTaskStatus.CANCELLED,
                artifact=None,
                error=None,
            )
            self.broker.mark_done(
                task_id,
                event_type=TaskEventType.TASK_CANCELLED,
                host_id=self.host_id,
                status=ResearchTaskStatus.CANCELLED,
                attempt_count=lease.attempt_count,
                fencing_token=lease.fencing_token,
                execution_id=lease.execution_id,
            )
            return
        if task.status is ResearchTaskStatus.RUNNING:
            self.task_store.update(
                task_id,
                status=ResearchTaskStatus.QUEUED,
                artifact=None,
                error=None,
            )
        try:
            monitor = WorkerLeaseMonitor(
                self.broker,
                lease,
                lease_seconds=self.lease_seconds,
            )
            monitor.start()
            self._lease_monitors[task_id] = monitor
            self.executor.submit_existing(
                task_id,
                lease.request,
                fencing_token=lease.fencing_token,
                execution_id=lease.execution_id,
                cancellation_token=monitor.cancellation_token,
            )
            self._task_started[task_id] = time.monotonic()
            self._task_attempts[task_id] = lease.attempt_count
            self._task_fences[task_id] = (
                lease.fencing_token,
                lease.execution_id,
            )
            self._task_leases[task_id] = lease.model_copy(deep=True)
            self.broker.record_event(
                task_id,
                TaskEventType.TASK_STARTED,
                ResearchTaskStatus.RUNNING,
                host_id=self.host_id,
                attempt_count=lease.attempt_count,
            )
            LOGGER.info(
                "task dispatched",
                extra={
                    "task_id": str(task_id),
                    "stage": "dispatch",
                    "status": ResearchTaskStatus.RUNNING.value,
                    "attempt_count": lease.attempt_count,
                },
            )
        except Exception as error:
            monitor = self._lease_monitors.pop(task_id, None)
            if monitor is not None:
                monitor.stop()
            current = self.task_store.get(task_id)
            if current.status is not ResearchTaskStatus.CANCELLED:
                self.task_store.update(
                    task_id,
                    status=ResearchTaskStatus.FAILED,
                    artifact=None,
                    error=f"host dispatch failed ({type(error).__name__})",
                )
            self.broker.mark_done(
                task_id,
                event_type=TaskEventType.TASK_FAILED,
                host_id=self.host_id,
                status=ResearchTaskStatus.FAILED,
                attempt_count=lease.attempt_count,
                fencing_token=lease.fencing_token,
                execution_id=lease.execution_id,
            )
            LOGGER.error(
                "task dispatch failed",
                extra={
                    "task_id": str(task_id),
                    "stage": "dispatch",
                    "status": ResearchTaskStatus.FAILED.value,
                },
            )

    def _finalize_dispatched(self) -> None:
        for task in self.task_store.list():
            if task.status in _TERMINAL_STATUSES:
                fence = self._task_fences.get(task.task_id)
                if fence is None:
                    continue
                monitor = self._lease_monitors.pop(task.task_id, None)
                if monitor is not None:
                    monitor.stop()
                event_type = _TERMINAL_EVENTS.get(task.status)
                duration_ms = self._duration_ms(task.task_id)
                attempt_count = self._task_attempts.get(task.task_id, 0)
                if (
                    task.status is ResearchTaskStatus.FAILED
                    and attempt_count >= self.max_attempts
                ):
                    lease = self._task_leases[task.task_id]
                    changed = self.dead_letter_service.move_failed(
                        task,
                        lease,
                        host_id=self.host_id,
                    )
                    if changed:
                        self._clear_execution(task.task_id)
                    continue
                changed = self.broker.mark_done(
                    task.task_id,
                    event_type=event_type,
                    host_id=self.host_id,
                    status=task.status,
                    attempt_count=self._task_attempts.get(task.task_id, 0),
                    duration_ms=duration_ms,
                    fencing_token=fence[0],
                    execution_id=fence[1],
                )
                if changed:
                    self._clear_execution(task.task_id)
                    LOGGER.info(
                        "task terminal",
                        extra={
                            "task_id": str(task.task_id),
                            "stage": "execution",
                            "duration_ms": duration_ms,
                            "status": task.status.value,
                        },
                    )

    def _duration_ms(self, task_id: UUID) -> float | None:
        started = self._task_started.get(task_id)
        if started is None:
            return None
        return max(0.0, (time.monotonic() - started) * 1000)

    def _clear_execution(self, task_id: UUID) -> None:
        self._task_started.pop(task_id, None)
        self._task_attempts.pop(task_id, None)
        self._task_fences.pop(task_id, None)
        self._task_leases.pop(task_id, None)

    def _stop_lease_monitors(self) -> None:
        for monitor in self._lease_monitors.values():
            monitor.stop()
        self._lease_monitors.clear()



def create_task_host_client(
    settings: RuntimeSettings,
) -> "PersistentTaskHostClient":
    """Create a lightweight client using the runtime's deterministic DB path."""

    from .client import PersistentTaskHostClient

    database_path = settings.task_database_path()
    return PersistentTaskHostClient(
        PersistentTaskStore(database_path),
        SQLiteHostBroker(database_path),
    )
