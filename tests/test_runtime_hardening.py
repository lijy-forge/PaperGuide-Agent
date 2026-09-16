"""Failure-oriented tests for distributed SQLite runtime hardening."""

import hashlib
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from paperguide.application import (
    ResearchRequest,
    ResearchTask,
    ResearchTaskStatus,
)
from paperguide.execution import (
    ExecutionCancellationToken,
    ExecutionContext,
    InMemoryTaskExecutor,
    PersistentTaskStore,
    execution_scope,
)
from paperguide.export import ArtifactMetadata, ExportFormat
from paperguide.runtime import MetricsExporter
from paperguide.runtime.host import (
    HostStatus,
    SQLiteHostBroker,
    TaskEventType,
    WorkerLeaseMonitor,
)

from tests.test_export_service import make_report, make_service


class RuntimeHardeningTests(unittest.TestCase):
    """Verify lease loss, DLQ, artifact isolation, metrics, and recovery."""

    def test_lease_monitor_automatically_renews_worker_lease(self) -> None:
        with self.runtime() as runtime:
            broker, _, task_id, host_id = runtime
            lease = broker.claim_next(host_id, lease_seconds=0.15)
            monitor = WorkerLeaseMonitor(
                broker,
                lease,
                lease_seconds=0.15,
                interval_seconds=0.02,
            )
            original_until = lease.lease_until
            monitor.start()
            time.sleep(0.07)
            monitor.stop()
            events = broker.list_events(task_id)

        self.assertFalse(monitor.cancellation_token.is_cancelled)
        self.assertIsNotNone(monitor.last_result)
        self.assertGreater(monitor.last_result.lease_until, original_until)
        self.assertIn(
            TaskEventType.LEASE_RENEWED,
            [event.event_type for event in events],
        )

    def test_expired_lease_cooperatively_stops_result_submission(self) -> None:
        with self.runtime() as runtime:
            broker, store, task_id, host_id = runtime
            lease = broker.claim_next(host_id, lease_seconds=0.04)
            application = BlockingApplicationService(store)
            executor = InMemoryTaskExecutor(application, store, max_workers=1)
            monitor = WorkerLeaseMonitor(
                broker,
                lease,
                lease_seconds=0.05,
                interval_seconds=0.005,
            )
            executor.submit_existing(
                task_id,
                lease.request,
                fencing_token=lease.fencing_token,
                execution_id=lease.execution_id,
                cancellation_token=monitor.cancellation_token,
            )
            self.assertTrue(application.started.wait(timeout=1))
            time.sleep(0.05)
            monitor.start()
            self.wait_until(lambda: monitor.cancellation_token.is_cancelled)
            application.release.set()
            time.sleep(0.05)
            executor.shutdown()
            monitor.stop()
            stored = store.get(task_id)
            event_types = [
                event.event_type for event in broker.list_events(task_id)
            ]

        self.assertEqual(stored.status, ResearchTaskStatus.RUNNING)
        self.assertIn(TaskEventType.LEASE_EXPIRED, event_types)
        self.assertIn(TaskEventType.EXECUTION_ABORTED, event_types)

    def test_old_worker_final_submission_is_rejected(self) -> None:
        with self.runtime() as runtime:
            broker, store, task_id, host_id = runtime
            first = broker.claim_next(host_id, lease_seconds=10)
            self.expire_lease(broker.database_path, task_id)
            second = broker.claim_next(host_id, lease_seconds=10)
            rejected = store.update_fenced(
                task_id,
                first.fencing_token,
                first.execution_id,
                status=ResearchTaskStatus.FAILED,
                artifact=None,
                error="stale worker (StaleWorker)",
            )
            accepted = store.update_fenced(
                task_id,
                second.fencing_token,
                second.execution_id,
                status=ResearchTaskStatus.RUNNING,
            )
            stale_events = [
                event
                for event in broker.list_events(task_id)
                if event.event_type is TaskEventType.STALE_WORKER_REJECTED
            ]

        self.assertIsNone(rejected)
        self.assertEqual(accepted.status, ResearchTaskStatus.RUNNING)
        self.assertEqual(len(stale_events), 1)

    def test_retry_limit_moves_task_to_dead_letter(self) -> None:
        with self.runtime() as runtime:
            broker, _, task_id, host_id = runtime
            broker.claim_next(host_id, lease_seconds=10)
            self.expire_lease(broker.database_path, task_id)
            broker.recover_incomplete(max_attempts=2)
            second = broker.claim_next(host_id, lease_seconds=10)
            self.expire_lease(broker.database_path, task_id)
            result = broker.recover_incomplete(max_attempts=2)

        self.assertEqual(second.attempt_count, 2)
        self.assertEqual(result.dead_lettered, [task_id])

    def test_dead_letter_query_returns_sanitized_record(self) -> None:
        with self.runtime() as runtime:
            broker, _, task_id, host_id = runtime
            lease = broker.claim_next(host_id)
            moved = broker.move_to_dead_letter(
                task_id,
                execution_id=lease.execution_id,
                last_status=ResearchTaskStatus.FAILED.value,
                last_error_type="TimeoutError",
                failed_stage="reader",
                attempt_count=lease.attempt_count,
                fencing_token=lease.fencing_token,
                host_id=host_id,
            )
            records = broker.list_dead_letters()

        self.assertTrue(moved)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].last_error_type, "TimeoutError")
        self.assertNotIn("api_key", records[0].model_dump_json())

    def test_artifacts_are_isolated_by_task_and_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_id = uuid4()
            service = make_service(directory)
            first = self.export_in_scope(service, task_id, 1)
            second = self.export_in_scope(service, task_id, 2)

        first_path = Path(first.file_path)
        second_path = Path(second.file_path)
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(first_path.parent.parent.name, str(task_id))
        self.assertEqual(first.artifact.execution_id, f"{task_id}:1")
        self.assertEqual(second.artifact.task_id, task_id)

    def test_repeated_execution_returns_existing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_id = uuid4()
            service = make_service(directory)
            first = self.export_in_scope(service, task_id, 1)
            service.markdown_exporter = FailingExporter()
            second = self.export_in_scope(service, task_id, 1)

        self.assertEqual(second.file_path, first.file_path)
        self.assertEqual(second.artifact.sha256, first.artifact.sha256)

    def test_json_metrics_include_runtime_lease_and_duration_values(self) -> None:
        with self.runtime() as runtime:
            broker, _, task_id, host_id = runtime
            lease = broker.claim_next(host_id)
            broker.mark_done(
                task_id,
                event_type=TaskEventType.TASK_COMPLETED,
                host_id=host_id,
                status=ResearchTaskStatus.COMPLETED,
                attempt_count=lease.attempt_count,
                duration_ms=120.0,
                fencing_token=lease.fencing_token,
                execution_id=lease.execution_id,
            )
            broker.record_event(
                task_id,
                TaskEventType.LEASE_EXPIRED,
                ResearchTaskStatus.RUNNING,
                attempt_count=2,
            )
            broker.record_event(
                task_id,
                TaskEventType.STALE_WORKER_REJECTED,
                ResearchTaskStatus.FAILED,
                attempt_count=2,
            )
            exporter = MetricsExporter(broker)
            metrics = exporter.get_metrics()
            payload = exporter.export_json()

        self.assertEqual(metrics.submitted_total, 1)
        self.assertEqual(metrics.completed_total, 1)
        self.assertEqual(metrics.lease_expired_total, 1)
        self.assertEqual(metrics.stale_worker_rejected_total, 1)
        self.assertEqual(metrics.average_execution_time_ms, 120.0)
        self.assertIn('"completed_total":1', payload)

    def test_crash_recovery_retains_valid_and_requeues_expired_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery.sqlite3"
            broker = SQLiteHostBroker(path)
            first_id = uuid4()
            second_id = uuid4()
            request = ResearchRequest(question="Recover runtime")
            broker.enqueue(first_id, request)
            broker.enqueue(second_id, request)
            first = broker.claim_next(uuid4(), lease_seconds=30)
            second = broker.claim_next(uuid4(), lease_seconds=30)
            self.expire_lease(path, second.task_id)
            recovery = broker.recover_incomplete(max_attempts=3)

        self.assertEqual(recovery.retained, [first.task_id])
        self.assertEqual(recovery.requeued, [second.task_id])

    def test_recovery_is_idempotent_and_does_not_duplicate_events(self) -> None:
        with self.runtime() as runtime:
            broker, _, task_id, host_id = runtime
            broker.claim_next(host_id, lease_seconds=10)
            self.expire_lease(broker.database_path, task_id)
            first = broker.recover_incomplete(max_attempts=3)
            second = broker.recover_incomplete(max_attempts=3)
            expired_events = [
                event
                for event in broker.list_events(task_id)
                if event.event_type is TaskEventType.LEASE_EXPIRED
            ]

        self.assertEqual(first.requeued, [task_id])
        self.assertEqual(second.requeued, [])
        self.assertEqual(len(expired_events), 1)

    def runtime(self):
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "runtime.sqlite3"
        store = PersistentTaskStore(path)
        broker = SQLiteHostBroker(path)
        host_id = uuid4()
        broker.acquire_host(host_id)
        broker.heartbeat(host_id, status=HostStatus.RUNNING)
        task = store.save(ResearchTask(run_id=uuid4(), question="Hardening"))
        store.update(task.task_id, status=ResearchTaskStatus.QUEUED)
        broker.enqueue(task.task_id, ResearchRequest(question=task.question))
        return RuntimeContext(temporary, broker, store, task.task_id, host_id)

    @staticmethod
    def expire_lease(path: Path, task_id: UUID) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "UPDATE task_requests SET lease_until = ? WHERE task_id = ?",
                (
                    (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                    str(task_id),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def wait_until(predicate, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        raise AssertionError("condition was not reached before timeout")

    @staticmethod
    def export_in_scope(service, task_id: UUID, attempt: int):
        execution_id = f"{task_id}:{attempt}"
        context = ExecutionContext(
            task_id=task_id,
            execution_id=execution_id,
            cancellation_token=ExecutionCancellationToken(),
        )
        with execution_scope(context):
            return service.export(make_report(), ExportFormat.MARKDOWN)


class RuntimeContext:
    def __init__(self, temporary, broker, store, task_id, host_id) -> None:
        self.temporary = temporary
        self.value = broker, store, task_id, host_id

    def __enter__(self):
        return self.value

    def __exit__(self, *exc_info) -> None:
        self.temporary.cleanup()


class BlockingApplicationService:
    def __init__(self, task_store) -> None:
        self.task_store = task_store
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, request):
        self.started.set()
        self.release.wait(timeout=1)
        payload = b"report"
        artifact = ArtifactMetadata(
            format=ExportFormat.MARKDOWN,
            file_path="report.md",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        return SimpleNamespace(
            task=ResearchTask(
                run_id=uuid4(),
                question=request.question,
                status=ResearchTaskStatus.COMPLETED,
                artifact=artifact,
            )
        )


class FailingExporter:
    def export(self, report):
        del report
        raise AssertionError("existing execution must not render twice")


if __name__ == "__main__":
    unittest.main()
