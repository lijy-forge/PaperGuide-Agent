"""Best-effort adapter from real workflow actions to persisted telemetry."""

import logging
from math import ceil
from time import monotonic
from typing import Protocol
from uuid import UUID

from .events import TaskEventType
from .models import ProgressAppendMetrics, ProgressEventPayload
from .validator import PublicProgressValidator

LOGGER = logging.getLogger("paperpilot.progress")


class ProgressPublisherProtocol(Protocol):
    """Publish public progress without affecting research control flow."""

    def bind(self, run_id: UUID, task_id: UUID) -> None: ...
    def unbind(self, run_id: UUID) -> None: ...
    def publish(self, run_id: UUID, event_type: TaskEventType, payload: ProgressEventPayload) -> None: ...

    def publish_diagnostic(
        self,
        run_id: UUID,
        event_type: TaskEventType,
        payload: dict[str, object],
        *,
        duration_ms: float | None = None,
        dedupe_key: str | None = None,
    ) -> None: ...


class ProgressBrokerProtocol(Protocol):
    """Minimal storage boundary needed by the best-effort publisher."""

    def record_progress_event(self, task_id: UUID, event_type: TaskEventType, status, progress: ProgressEventPayload, *, dedupe_key: str): ...


class ProgressPublisher:
    """Persist validated stage events with per-run logical idempotency."""

    def __init__(self, broker: ProgressBrokerProtocol, validator: PublicProgressValidator | None = None) -> None:
        self.broker = broker
        self.validator = validator or PublicProgressValidator()
        self._task_by_run: dict[UUID, UUID] = {}
        self._started: dict[tuple[UUID, str], float] = {}
        self._append_latencies_ms: list[float] = []

    def bind(self, run_id: UUID, task_id: UUID) -> None:
        self._task_by_run[run_id] = task_id

    def unbind(self, run_id: UUID) -> None:
        self._task_by_run.pop(run_id, None)
        for key in [key for key in self._started if key[0] == run_id]:
            self._started.pop(key, None)

    def publish(self, run_id: UUID, event_type: TaskEventType, payload: ProgressEventPayload) -> None:
        """Append one safe event; telemetry failure is intentionally non-fatal."""

        task_id = self._task_by_run.get(run_id)
        if task_id is None:
            return
        try:
            safe = self.validator.validate(payload)
            stage_key = safe.stage.value
            now = monotonic()
            if event_type.value.endswith("_started"):
                self._started[(run_id, stage_key)] = now
            elapsed = safe.elapsed_ms
            if elapsed is None and event_type.value.endswith(("_completed", "_progress")):
                started = self._started.get((run_id, stage_key))
                if started is not None:
                    elapsed = max(0.0, (now - started) * 1000)
                    safe = safe.model_copy(update={"elapsed_ms": elapsed})
            append_started = monotonic()
            self.broker.record_progress_event(
                task_id,
                event_type,
                self._running_status(),
                safe,
                dedupe_key=self._dedupe_key(event_type, safe),
            )
            self._append_latencies_ms.append((monotonic() - append_started) * 1000)
        except Exception as error:
            LOGGER.warning("progress event omitted", extra={"event_type": event_type.value, "error_type": type(error).__name__})

    def publish_diagnostic(
        self,
        run_id: UUID,
        event_type: TaskEventType,
        payload: dict[str, object],
        *,
        duration_ms: float | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        """Best-effort private diagnostic event; never affects workflow."""

        task_id = self._task_by_run.get(run_id)
        if task_id is None:
            return
        try:
            recorder = getattr(self.broker, "record_diagnostic_event", None)
            if recorder is None:
                return
            recorder(
                task_id,
                event_type,
                self._running_status(),
                payload,
                duration_ms=duration_ms,
                dedupe_key=dedupe_key,
            )
        except Exception as error:
            LOGGER.warning(
                "diagnostic event omitted",
                extra={"event_type": event_type.value, "error_type": type(error).__name__},
            )

    def append_metrics(self) -> ProgressAppendMetrics:
        """Return local append latency summary without exposing event payloads."""

        samples = sorted(self._append_latencies_ms)
        if not samples:
            return ProgressAppendMetrics()
        index = max(0, ceil(len(samples) * 0.95) - 1)
        return ProgressAppendMetrics(
            count=len(samples),
            mean_latency_ms=sum(samples) / len(samples),
            p95_latency_ms=samples[index],
        )

    @staticmethod
    def _dedupe_key(event_type: TaskEventType, payload: ProgressEventPayload) -> str:
        return ":".join(
            [event_type.value, payload.stage.value, str(payload.completed), str(payload.total)]
        )

    @staticmethod
    def _running_status():
        # Deferred to avoid an application/progress import cycle at bootstrap.
        from paperpilot.application.models import ResearchTaskStatus

        return ResearchTaskStatus.RUNNING
