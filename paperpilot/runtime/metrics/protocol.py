"""Storage-neutral runtime metrics exporter protocol."""

from typing import Protocol

from .models import RuntimeMetricsSnapshot


class MetricsExporterProtocol(Protocol):
    """Return one deterministic runtime metrics snapshot."""

    def get_metrics(self) -> RuntimeMetricsSnapshot:
        """Collect current counters and gauges."""

        ...
