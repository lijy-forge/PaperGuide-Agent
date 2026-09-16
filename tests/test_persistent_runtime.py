"""Tests for SQLite task persistence and the long-lived local TaskHost."""

import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from paperguide.application import (
    ResearchRequest,
    ResearchTask,
    ResearchTaskStatus,
    TaskStoreProtocol,
)
from paperguide.execution import PersistentTaskStore
from paperguide.export import ArtifactMetadata, ExportFormat
from paperguide.runtime import RuntimeSettings, run_cli
from paperguide.runtime.host import (
    PersistentTaskHostClient,
    SQLiteHostBroker,
    TaskHost,
)


def make_artifact(name: str = "persistent-report.md") -> ArtifactMetadata:
    payload = name.encode("utf-8")
    return ArtifactMetadata(
        format=ExportFormat.MARKDOWN,
        file_path=name,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def make_settings(root: Path) -> RuntimeSettings:
    return RuntimeSettings(
        model_name="fake-model",
        llm_provider="fake-provider",
        export_directory=root / "exports",
        max_papers=5,
        log_level="ERROR",
    )


class FakeApplicationService:
    """Return deterministic application tasks or a configured safe test failure."""

    def __init__(self, task_store, *, error=None):
        self.task_store = task_store
        self.error = error
        self.requests = []
        self._lock = threading.Lock()

    def run(self, request):
        with self._lock:
            self.requests.append(request.model_copy(deep=True))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            task=ResearchTask(
                run_id=uuid4(),
                question=request.question,
                status=ResearchTaskStatus.COMPLETED,
                artifact=make_artifact(),
            )
        )


class FakeApplicationFactory:
    """Build a container around the exact persistent store injected by TaskHost."""

    def __init__(self, *, error=None):
        self.error = error
        self.calls = []
        self.service = None

    def __call__(self, config, *, task_store):
        self.calls.append((config.model_copy(deep=True), task_store))
        self.service = FakeApplicationService(task_store, error=self.error)
        return SimpleNamespace(
            application_service=self.service,
            task_store=task_store,
        )


def start_host(root: Path, *, error=None):
    """Start one fake-backed TaskHost and wait for its SQLite heartbeat."""

    settings = make_settings(root)
    database_path = root / "runtime.sqlite3"
    factory = FakeApplicationFactory(error=error)
    host = TaskHost(
        settings,
        database_path=database_path,
        application_factory=factory,
        poll_interval=0.01,
        heartbeat_ttl=1,
    )
    thread = threading.Thread(target=host.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if host.broker.host_available():
            client = PersistentTaskHostClient(host.task_store, host.broker)
            return host, thread, client, factory
        time.sleep(0.005)
    host.shutdown()
    thread.join(timeout=2)
    raise AssertionError("task host did not publish a heartbeat")


def stop_host(host, thread):
    host.shutdown()
    thread.join(timeout=3)
    if thread.is_alive():
        raise AssertionError("task host did not stop")


def wait_terminal(client, task_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        task = client.get_status(task_id)
        if task.status in {
            ResearchTaskStatus.COMPLETED,
            ResearchTaskStatus.FAILED,
            ResearchTaskStatus.HUMAN_REVIEW,
        }:
            return task
        time.sleep(0.005)
    raise AssertionError("persistent task did not reach a terminal state")


class PersistentRuntimeTests(unittest.TestCase):
    """Verify durable storage, host dispatch, isolation, and safe failures."""

    def test_sqlite_task_save_get_update_delete_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PersistentTaskStore(Path(directory) / "tasks.sqlite3")
            first = store.save(
                ResearchTask(run_id=uuid4(), question="First task")
            )
            second = store.save(
                ResearchTask(run_id=uuid4(), question="Second task")
            )
            loaded = store.get(first.task_id)
            updated = store.update(
                first.task_id,
                status=ResearchTaskStatus.RUNNING,
            )

            self.assertIsInstance(store, TaskStoreProtocol)
            self.assertEqual(loaded, first)
            self.assertIsNot(loaded, first)
            self.assertIsNotNone(loaded.created_at.tzinfo)
            self.assertIsNotNone(updated.updated_at.tzinfo)
            self.assertEqual(
                {task.task_id for task in store.list()},
                {first.task_id, second.task_id},
            )
            self.assertTrue(store.delete(second.task_id))
            self.assertFalse(store.delete(second.task_id))

    def test_task_survives_store_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.sqlite3"
            original_store = PersistentTaskStore(path)
            task = original_store.save(
                ResearchTask(run_id=uuid4(), question="Persistent task")
            )

            restarted_store = PersistentTaskStore(path)
            restarted = restarted_store.get(task.task_id)

        self.assertEqual(restarted, task)
        self.assertIsNotNone(restarted.created_at.utcoffset())

    def test_submit_then_status_query_and_worker_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            host, thread, client, factory = start_host(Path(directory))
            try:
                handle = client.submit(
                    ResearchRequest(question="Analyze persistent SLAM")
                )
                initial = client.get_status(handle.task_id)
                completed = wait_terminal(client, handle.task_id)
            finally:
                stop_host(host, thread)

        self.assertIn(
            initial.status,
            (
                ResearchTaskStatus.QUEUED,
                ResearchTaskStatus.RUNNING,
                ResearchTaskStatus.COMPLETED,
            ),
        )
        self.assertEqual(completed.status, ResearchTaskStatus.COMPLETED)
        self.assertIsNotNone(completed.artifact)
        self.assertEqual(
            factory.service.requests[0].question,
            "Analyze persistent SLAM",
        )

    def test_worker_failure_is_persisted_without_secret(self) -> None:
        secret = "api_key=do-not-store"
        with tempfile.TemporaryDirectory() as directory:
            host, thread, client, _ = start_host(
                Path(directory),
                error=RuntimeError(secret),
            )
            try:
                handle = client.submit(ResearchRequest(question="Fail safely"))
                failed = wait_terminal(client, handle.task_id)
                restarted = PersistentTaskStore(host.database_path).get(
                    handle.task_id
                )
            finally:
                stop_host(host, thread)

        self.assertEqual(failed.status, ResearchTaskStatus.FAILED)
        self.assertIn("RuntimeError", failed.error)
        self.assertNotIn(secret, failed.error)
        self.assertEqual(restarted, failed)

    def test_multiple_persistent_tasks_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            host, thread, client, _ = start_host(Path(directory))
            try:
                handles = [
                    client.submit(ResearchRequest(question=f"Question {index}"))
                    for index in range(3)
                ]
                completed = [
                    wait_terminal(client, handle.task_id) for handle in handles
                ]
            finally:
                stop_host(host, thread)

        self.assertEqual(len({handle.task_id for handle in handles}), 3)
        self.assertEqual(
            {task.question for task in completed},
            {"Question 0", "Question 1", "Question 2"},
        )
        self.assertTrue(
            all(task.status is ResearchTaskStatus.COMPLETED for task in completed)
        )

    def test_sqlite_payload_does_not_contain_worker_secret(self) -> None:
        secret = "password=raw-secret-value"
        with tempfile.TemporaryDirectory() as directory:
            host, thread, client, _ = start_host(
                Path(directory),
                error=ValueError(secret),
            )
            try:
                handle = client.submit(ResearchRequest(question="Secret failure"))
                wait_terminal(client, handle.task_id)
            finally:
                stop_host(host, thread)
            database_bytes = host.database_path.read_bytes()

        self.assertNotIn(secret.encode("utf-8"), database_bytes)

    def test_cli_submit_without_host_returns_explicit_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            errors = io.StringIO()
            exit_code = run_cli(
                ["research", "submit", "Question"],
                settings_loader=lambda: make_settings(Path(directory)),
                stdout=output,
                stderr=errors,
            )

        payload = json.loads(errors.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            payload["error"],
            "task host is unavailable; run 'paperguide server start'",
        )

    def test_server_start_cli_uses_injected_host(self) -> None:
        class FakeHost:
            def __init__(self):
                self.served = False

            def serve_forever(self):
                self.served = True

            def shutdown(self):
                pass

        fake_host = FakeHost()
        with tempfile.TemporaryDirectory() as directory:
            exit_code = run_cli(
                ["server", "start"],
                settings_loader=lambda: make_settings(Path(directory)),
                task_host_factory=lambda settings: fake_host,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(fake_host.served)


if __name__ == "__main__":
    unittest.main()
