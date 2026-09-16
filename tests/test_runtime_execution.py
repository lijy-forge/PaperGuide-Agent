"""Tests for TaskExecutor integration with the PaperGuide runtime CLI."""

import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from paperguide.application import (
    InMemoryTaskStore,
    ResearchRequest,
    ResearchTask,
    ResearchTaskStatus,
    TaskNotFoundError,
)
from paperguide.execution import InMemoryTaskExecutor, TaskHandle
from paperguide.export import ArtifactMetadata, ExportFormat
from paperguide.runtime import RuntimeSettings, run_cli


def make_settings(root: Path) -> RuntimeSettings:
    return RuntimeSettings(
        model_name="fake-model",
        llm_provider="fake-provider",
        export_directory=root / "exports",
        max_papers=6,
        log_level="ERROR",
    )


def make_artifact() -> ArtifactMetadata:
    payload = b"report"
    return ArtifactMetadata(
        format=ExportFormat.MARKDOWN,
        file_path=str(Path("private/output/report.md").resolve()),
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def make_task(
    task_id: UUID,
    status: ResearchTaskStatus,
    *,
    question: str = "Question",
    error: str | None = None,
) -> ResearchTask:
    return ResearchTask(
        task_id=task_id,
        run_id=uuid4(),
        question=question,
        status=status,
        artifact=make_artifact() if status is ResearchTaskStatus.COMPLETED else None,
        error=error,
    )


class FakeTaskExecutor:
    """Controllable in-process executor for CLI integration tests."""

    def __init__(self):
        self.task_id = uuid4()
        self.requests = []
        self.statuses = [make_task(self.task_id, ResearchTaskStatus.QUEUED)]
        self.status_calls = 0
        self.cancel_calls = []
        self.error = None

    def submit(self, request):
        self.requests.append(request.model_copy(deep=True))
        return TaskHandle(
            task_id=self.task_id,
            status=ResearchTaskStatus.QUEUED,
        )

    def get_status(self, task_id):
        if self.error is not None:
            raise self.error
        if task_id != self.task_id:
            raise TaskNotFoundError("task not found")
        index = min(self.status_calls, len(self.statuses) - 1)
        self.status_calls += 1
        return self.statuses[index].model_copy(deep=True)

    def cancel(self, task_id):
        self.cancel_calls.append(task_id)
        if task_id != self.task_id:
            raise TaskNotFoundError("task not found")
        return make_task(task_id, ResearchTaskStatus.CANCELLED)


class BlockingApplicationService:
    """Keep one worker occupied so a second Future remains cancellable."""

    def __init__(self, store, release):
        self.task_store = store
        self.release = release
        self.started = threading.Event()
        self.requests = []

    def run(self, request):
        self.requests.append(request.model_copy(deep=True))
        self.started.set()
        self.release.wait(timeout=2)
        task = make_task(uuid4(), ResearchTaskStatus.COMPLETED)
        return SimpleNamespace(task=task)


class RuntimeExecutionTests(unittest.TestCase):
    """Verify submit, query, wait, cancellation, and safe CLI failures."""

    def test_submit_cli_returns_task_handle(self) -> None:
        executor = FakeTaskExecutor()
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            exit_code = run_cli(
                ["research", "submit", "Analyze SLAM", "--max-papers", "4"],
                settings_loader=lambda: make_settings(Path(directory)),
                task_executor=executor,
                stdout=output,
                stderr=io.StringIO(),
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["task_id"], str(executor.task_id))
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(executor.requests[0].question, "Analyze SLAM")
        self.assertEqual(executor.requests[0].max_papers, 4)

    def test_status_cli_queries_executor_store(self) -> None:
        executor = FakeTaskExecutor()
        executor.statuses = [make_task(executor.task_id, ResearchTaskStatus.RUNNING)]
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            exit_code = run_cli(
                ["task", "status", str(executor.task_id)],
                settings_loader=lambda: make_settings(Path(directory)),
                task_executor=executor,
                stdout=output,
                stderr=io.StringIO(),
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "running")
        self.assertEqual(executor.status_calls, 1)

    def test_wait_cli_polls_until_completed(self) -> None:
        executor = FakeTaskExecutor()
        executor.statuses = [
            make_task(executor.task_id, ResearchTaskStatus.RUNNING),
            make_task(executor.task_id, ResearchTaskStatus.COMPLETED),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            exit_code = run_cli(
                [
                    "task",
                    "wait",
                    str(executor.task_id),
                    "--poll-interval",
                    "0",
                ],
                settings_loader=lambda: make_settings(Path(directory)),
                task_executor=executor,
                stdout=output,
                stderr=io.StringIO(),
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifact"], "report.md")
        self.assertGreaterEqual(executor.status_calls, 2)

    def test_cancel_cli_delegates_to_executor(self) -> None:
        executor = FakeTaskExecutor()
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            exit_code = run_cli(
                ["task", "cancel", str(executor.task_id)],
                settings_loader=lambda: make_settings(Path(directory)),
                task_executor=executor,
                stdout=output,
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "cancelled")
        self.assertEqual(executor.cancel_calls, [executor.task_id])

    def test_task_not_found_is_safely_reported(self) -> None:
        executor = FakeTaskExecutor()
        secret = "token=do-not-expose"
        executor.error = TaskNotFoundError(secret)
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            errors = io.StringIO()
            exit_code = run_cli(
                ["task", "status", str(executor.task_id)],
                settings_loader=lambda: make_settings(Path(directory)),
                task_executor=executor,
                stdout=output,
                stderr=errors,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn(secret, errors.getvalue())
        self.assertIn("TaskNotFoundError", errors.getvalue())

    def test_failed_task_does_not_expose_stored_error(self) -> None:
        executor = FakeTaskExecutor()
        secret = "password=do-not-expose"
        executor.statuses = [
            make_task(
                executor.task_id,
                ResearchTaskStatus.FAILED,
                error=secret,
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            exit_code = run_cli(
                ["task", "status", str(executor.task_id)],
                settings_loader=lambda: make_settings(Path(directory)),
                task_executor=executor,
                stdout=output,
                stderr=io.StringIO(),
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["error"], "task execution failed")
        self.assertNotIn(secret, output.getvalue())

    def test_queued_task_can_be_cancelled_before_start(self) -> None:
        store = InMemoryTaskStore()
        release = threading.Event()
        service = BlockingApplicationService(store, release)
        executor = InMemoryTaskExecutor(service, store, max_workers=1)
        try:
            first = executor.submit(ResearchRequest(question="First"))
            self.assertTrue(service.started.wait(timeout=1))
            second = executor.submit(ResearchRequest(question="Second"))

            cancelled = executor.cancel(second.task_id)

            self.assertEqual(cancelled.status, ResearchTaskStatus.CANCELLED)
            self.assertEqual(
                executor.get_status(second.task_id).status,
                ResearchTaskStatus.CANCELLED,
            )
            self.assertEqual(
                executor.get_status(first.task_id).status,
                ResearchTaskStatus.RUNNING,
            )
        finally:
            release.set()
            executor.shutdown()
        self.assertEqual(
            [request.question for request in service.requests],
            ["First"],
        )

    def test_running_task_records_cancel_request_without_forced_stop(self) -> None:
        store = InMemoryTaskStore()
        release = threading.Event()
        service = BlockingApplicationService(store, release)
        executor = InMemoryTaskExecutor(service, store, max_workers=1)
        try:
            handle = executor.submit(ResearchRequest(question="Running"))
            self.assertTrue(service.started.wait(timeout=1))

            requested = executor.cancel(handle.task_id)

            self.assertEqual(
                requested.status,
                ResearchTaskStatus.CANCEL_REQUESTED,
            )
            release.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                completed = executor.get_status(handle.task_id)
                if completed.status is ResearchTaskStatus.COMPLETED:
                    break
                time.sleep(0.005)
            else:
                self.fail("running task did not finish after cancellation request")
        finally:
            release.set()
            executor.shutdown()


if __name__ == "__main__":
    unittest.main()
