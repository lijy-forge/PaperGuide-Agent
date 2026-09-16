"""Cooperative worker lease monitoring for fenced task executions."""

from threading import Event, Thread
from typing import Protocol

from paperguide.execution import ExecutionCancellationToken

from .broker import SQLiteHostBroker
from .models import LeaseRenewalResult, TaskLease


class LeaseMonitorProtocol(Protocol):
    """Lifecycle boundary for one worker lease monitor."""

    @property
    def cancellation_token(self) -> ExecutionCancellationToken:
        """Return the token workers inspect at cooperative boundaries."""

        ...

    def start(self) -> None:
        """Start periodic lease validation and renewal."""

        ...

    def stop(self) -> None:
        """Stop monitoring and wait for its helper thread."""

        ...


class WorkerLeaseMonitor:
    """Renew one lease and cooperatively cancel work when ownership is lost."""

    def __init__(
        self,
        broker: SQLiteHostBroker,
        lease: TaskLease,
        *,
        lease_seconds: float,
        interval_seconds: float | None = None,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        interval = interval_seconds or max(0.001, lease_seconds / 3)
        if interval <= 0 or interval >= lease_seconds:
            raise ValueError("monitor interval must be below lease duration")
        self.broker = broker
        self.lease = lease.model_copy(deep=True)
        self.lease_seconds = lease_seconds
        self.interval_seconds = interval
        self._token = ExecutionCancellationToken()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self.last_result: LeaseRenewalResult | None = None

    @property
    def cancellation_token(self) -> ExecutionCancellationToken:
        return self._token

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._thread = Thread(
            target=self._run,
            name=f"paperguide-lease-{self.lease.task_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 2))

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                result = self.broker.renew_task_lease(
                    self.lease.task_id,
                    self.lease.lease_owner,
                    self.lease.fencing_token,
                    lease_seconds=self.lease_seconds,
                )
            except Exception:
                self._abort()
                return
            self.last_result = result
            if not result.renewed:
                self._abort()
                return

    def _abort(self) -> None:
        self._token.cancel()
        self.broker.record_execution_aborted(self.lease)
