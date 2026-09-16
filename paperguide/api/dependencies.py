"""Injected lightweight runtime dependencies for the API process."""

import importlib.util
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import Request

from paperguide.application import TaskStoreProtocol
from paperguide.execution import PersistentTaskStore
from paperguide.runtime import RuntimeSettings
from paperguide.runtime.host import (
    CURRENT_SCHEMA_VERSION,
    PersistentTaskHostClient,
    SQLiteHostBroker,
)
from paperguide.runtime.metrics import MetricsExporter, MetricsExporterProtocol

from .schemas import APISettings, HealthCheckResponse, HealthResponse

LOCAL_DASHBOARD_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


class RuntimeHealthCheckerProtocol(Protocol):
    """Return one safe readiness result without constructing application code."""

    def check(self) -> HealthResponse:
        """Check only API-facing runtime dependencies."""

        ...


@dataclass(frozen=True, slots=True)
class APIDependencies:
    """Already-created lightweight objects used by route handlers."""

    task_host_client: PersistentTaskHostClient
    task_store: TaskStoreProtocol
    broker: SQLiteHostBroker
    metrics_exporter: MetricsExporterProtocol
    runtime_health_checker: RuntimeHealthCheckerProtocol
    settings: APISettings
    artifact_root: Path


class APIRuntimeHealthChecker:
    """Check SQLite, Host, artifacts, schema, and API dependencies."""

    def __init__(self, broker: SQLiteHostBroker, artifact_root: Path) -> None:
        self.broker = broker
        self.artifact_root = artifact_root

    def check(self) -> HealthResponse:
        checks = [
            HealthCheckResponse(
                name="sqlite_runtime",
                healthy=self._sqlite_available(),
            ),
            HealthCheckResponse(
                name="host_heartbeat",
                healthy=self._host_available(),
            ),
            HealthCheckResponse(
                name="artifact_directory",
                healthy=self._artifact_writable(),
            ),
            HealthCheckResponse(
                name="api_dependencies",
                healthy=importlib.util.find_spec("fastapi") is not None,
            ),
            HealthCheckResponse(
                name="schema_version",
                healthy=self._schema_available(),
            ),
        ]
        ready = all(check.healthy for check in checks)
        return HealthResponse(
            kind="readiness",
            status="healthy" if ready else "unhealthy",
            ready=ready,
            checks=checks,
        )

    def _sqlite_available(self) -> bool:
        try:
            self.broker.schema_version()
            return True
        except Exception:
            return False

    def _host_available(self) -> bool:
        try:
            return self.broker.host_available()
        except Exception:
            return False

    def _schema_available(self) -> bool:
        try:
            return self.broker.schema_version() == CURRENT_SCHEMA_VERSION
        except Exception:
            return False

    def _artifact_writable(self) -> bool:
        try:
            self.artifact_root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.artifact_root,
                prefix=".api-health-",
                delete=True,
            ):
                return True
        except OSError:
            return False


def create_default_dependencies(
    api_settings: APISettings | None = None,
    runtime_settings: RuntimeSettings | None = None,
) -> APIDependencies:
    """Create clients and stores only; never create Host, Graph, or Executor."""

    runtime = runtime_settings or RuntimeSettings.from_env()
    settings = api_settings or APISettings(
        artifact_root=runtime.export_directory,
        # The local Vite dashboard is served from a different development
        # origin. Keep this allowlist narrow; explicit APISettings still take
        # full control for deployments with a different dashboard origin.
        cors_allowed_origins=list(LOCAL_DASHBOARD_ORIGINS),
    )
    artifact_root = Path(settings.artifact_root).resolve(strict=False)
    database_path = runtime.task_database_path()
    store = PersistentTaskStore(database_path)
    broker = SQLiteHostBroker(database_path)
    client = PersistentTaskHostClient(store, broker)
    return APIDependencies(
        task_host_client=client,
        task_store=store,
        broker=broker,
        metrics_exporter=MetricsExporter(broker),
        runtime_health_checker=APIRuntimeHealthChecker(broker, artifact_root),
        settings=settings,
        artifact_root=artifact_root,
    )


def get_api_dependencies(request: Request) -> APIDependencies:
    """Resolve the dependency container stored on the FastAPI application."""

    return request.app.state.paperguide_dependencies
