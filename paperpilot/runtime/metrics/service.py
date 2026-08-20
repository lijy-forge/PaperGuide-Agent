"""Dependency-free JSON runtime metrics exporter."""

from paperpilot.runtime.host import SQLiteHostBroker

from .models import RuntimeMetricsSnapshot


class MetricsExporter:
    """Map SQLite broker counters into a stable JSON metrics contract."""

    def __init__(self, broker: SQLiteHostBroker) -> None:
        self.broker = broker

    def get_metrics(self) -> RuntimeMetricsSnapshot:
        metrics = self.broker.get_metrics()
        return RuntimeMetricsSnapshot(
            submitted_total=metrics.submitted,
            completed_total=metrics.completed,
            failed_total=metrics.failed,
            cancelled_total=metrics.cancelled,
            dead_letter_total=metrics.dead_letter_total,
            active_workers=metrics.active_workers,
            queue_size=metrics.queue_size,
            running_tasks=metrics.running_tasks,
            lease_expired_total=metrics.lease_expired_total,
            stale_worker_rejected_total=metrics.stale_worker_rejected_total,
            average_execution_time_ms=metrics.average_execution_time_ms,
        )

    def export_json(self) -> str:
        """Return compact JSON without introducing a metrics SDK."""

        return self.get_metrics().model_dump_json()
