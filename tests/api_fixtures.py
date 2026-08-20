"""Shared temporary SQLite and artifact fixtures for API tests."""

import hashlib
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from paperpilot.api import APISettings, create_api_app
from paperpilot.api.schemas import HealthCheckResponse, HealthResponse
from paperpilot.application import ResearchTask, ResearchTaskStatus
from paperpilot.execution import PersistentTaskStore
from paperpilot.export import ArtifactMetadata, ExportFormat
from paperpilot.runtime import MetricsExporter
from paperpilot.runtime.host import (
    HostStatus,
    PersistentTaskHostClient,
    SQLiteHostBroker,
)


class FakeHealthChecker:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready

    def check(self) -> HealthResponse:
        return HealthResponse(
            kind="readiness",
            status="healthy" if self.ready else "unhealthy",
            ready=self.ready,
            checks=[
                HealthCheckResponse(name="runtime", healthy=self.ready),
            ],
        )


class FailingMetricsExporter:
    def get_metrics(self):
        raise RuntimeError("database_path=C:/private/runtime.sqlite3")


class APITestRuntime:
    def __init__(
        self,
        *,
        ready: bool = True,
        max_question_length: int = 4000,
        max_event_page_size: int = 100,
        cors_origins: list[str] | None = None,
        metrics_exporter=None,
        raise_server_exceptions: bool = True,
    ) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.artifact_root = root / "artifacts"
        self.artifact_root.mkdir()
        self.database_path = root / "runtime.sqlite3"
        self.store = PersistentTaskStore(self.database_path)
        self.broker = SQLiteHostBroker(self.database_path)
        self.host_id = uuid4()
        self.broker.acquire_host(self.host_id)
        self.broker.heartbeat(self.host_id, status=HostStatus.RUNNING)
        self.host_client = PersistentTaskHostClient(self.store, self.broker)
        self.health_checker = FakeHealthChecker(ready=ready)
        settings = APISettings(
            artifact_root=self.artifact_root,
            max_question_length=max_question_length,
            max_event_page_size=max_event_page_size,
            cors_allowed_origins=cors_origins or [],
        )
        self.app = create_api_app(
            task_host_client=self.host_client,
            task_store=self.store,
            broker=self.broker,
            metrics_exporter=metrics_exporter or MetricsExporter(self.broker),
            runtime_health_checker=self.health_checker,
            artifact_root=self.artifact_root,
            api_settings=settings,
        )
        self.client = TestClient(
            self.app,
            raise_server_exceptions=raise_server_exceptions,
        )

    def close(self) -> None:
        self.client.close()
        self.temporary.cleanup()

    def save_task(
        self,
        status: ResearchTaskStatus,
        *,
        error: str | None = None,
        artifact: ArtifactMetadata | None = None,
    ) -> ResearchTask:
        return self.store.save(
            ResearchTask(
                run_id=uuid4(),
                question="Sensitive research question",
                status=status,
                artifact=artifact,
                error=error,
            )
        )

    def completed_task(
        self,
        export_format: ExportFormat,
        *,
        content: bytes = b"report",
        path: Path | None = None,
    ) -> ResearchTask:
        task_id = uuid4()
        suffix = {
            ExportFormat.MARKDOWN: ".md",
            ExportFormat.HTML: ".html",
            ExportFormat.PDF: ".pdf",
        }[export_format]
        target = path or self.artifact_root / str(task_id) / f"report{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        artifact = ArtifactMetadata(
            format=export_format,
            file_path=str(target),
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            task_id=task_id,
            execution_id=f"{task_id}:1",
        )
        return self.store.save(
            ResearchTask(
                task_id=task_id,
                run_id=uuid4(),
                question="Sensitive research question",
                status=ResearchTaskStatus.COMPLETED,
                artifact=artifact,
            )
        )

    def release_host(self) -> None:
        self.broker.release_host(self.host_id, status=HostStatus.STOPPED)


def response_has_no_sensitive_text(payload: object, *values: str) -> bool:
    serialized = str(payload)
    return all(value not in serialized for value in values)
