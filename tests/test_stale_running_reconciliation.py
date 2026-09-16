"""Regression tests for independent stale-running task reconciliation."""

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
from paperguide.execution import PersistentTaskStore
from paperguide.export import ArtifactMetadata, ExportFormat
from paperguide.runtime import RuntimeSettings
from paperguide.runtime.host import (
    HostStatus,
    RuntimeReconciler,
    RuntimeRecoveryService,
    SQLiteHostBroker,
    TaskEventType,
    TaskHost,
)


class StaleRunningReconciliationTests(unittest.TestCase):
    """Exercise the H0 alive-but-stale failure through the real recovery path."""

    def test_alive_but_stale_host_task_is_requeued_by_independent_loop(self) -> None:
        with self.runtime() as runtime:
            broker, store, task_id, host_id, lease = runtime
            self.make_host_stale(broker.database_path, host_id)
            self.expire_lease(broker.database_path, task_id)
            reconciler = self.reconciler(broker, store, interval=0.01)

            reconciler.start()
            self.wait_until(
                lambda: store.get(task_id).status is ResearchTaskStatus.QUEUED
            )
            reconciler.stop()

            events = broker.list_events(task_id)
            request = self.request_row(broker.database_path, task_id)

        self.assertFalse(reconciler.is_running)
        self.assertEqual(request[0], "queued")
        self.assertEqual(request[1], lease.attempt_count)
        self.assertIn(TaskEventType.LEASE_EXPIRED, self.event_types(events))

    def test_dead_host_task_is_requeued(self) -> None:
        with self.runtime() as runtime:
            broker, store, task_id, host_id, _ = runtime
            broker.release_host(host_id, status=HostStatus.FAILED)
            self.expire_lease(broker.database_path, task_id)

            result = self.reconciler(broker, store).reconcile_once()
            status = store.get(task_id).status

        self.assertEqual(result.requeued, [task_id])
        self.assertEqual(status, ResearchTaskStatus.QUEUED)

    def test_fresh_host_with_active_lease_is_untouched(self) -> None:
        with self.runtime(lease_seconds=60) as runtime:
            broker, store, task_id, _, lease = runtime

            result = self.reconciler(broker, store).reconcile_once()
            request = self.request_row(broker.database_path, task_id)
            status = store.get(task_id).status

        self.assertEqual(result.retained, [task_id])
        self.assertEqual(status, ResearchTaskStatus.RUNNING)
        self.assertEqual(request, ("dispatched", lease.attempt_count))

    def test_stale_host_with_active_lease_is_not_preempted(self) -> None:
        with self.runtime(lease_seconds=60) as runtime:
            broker, store, task_id, host_id, _ = runtime
            self.make_host_stale(broker.database_path, host_id)

            result = self.reconciler(broker, store).reconcile_once()
            status = store.get(task_id).status

        self.assertEqual(result.retained, [task_id])
        self.assertEqual(status, ResearchTaskStatus.RUNNING)

    def test_expired_lease_with_fresh_host_uses_existing_recovery_rule(self) -> None:
        with self.runtime() as runtime:
            broker, store, task_id, _, _ = runtime
            self.expire_lease(broker.database_path, task_id)

            result = self.reconciler(broker, store).reconcile_once()
            status = store.get(task_id).status

        self.assertEqual(result.requeued, [task_id])
        self.assertEqual(status, ResearchTaskStatus.QUEUED)

    def test_two_reconcilers_produce_one_transition_and_event(self) -> None:
        with self.runtime() as runtime:
            broker, store, task_id, _, _ = runtime
            self.expire_lease(broker.database_path, task_id)
            first = self.reconciler(
                SQLiteHostBroker(broker.database_path),
                PersistentTaskStore(broker.database_path),
            )
            second = self.reconciler(
                SQLiteHostBroker(broker.database_path),
                PersistentTaskStore(broker.database_path),
            )
            barrier = threading.Barrier(3)
            results = []

            def run(reconciler):
                barrier.wait()
                results.append(reconciler.reconcile_once())

            threads = [
                threading.Thread(target=run, args=(first,)),
                threading.Thread(target=run, args=(second,)),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=2)

            expired_events = [
                event
                for event in broker.list_events(task_id)
                if event.event_type is TaskEventType.LEASE_EXPIRED
            ]
            status = store.get(task_id).status

        self.assertEqual(sum(task_id in item.requeued for item in results), 1)
        self.assertEqual(status, ResearchTaskStatus.QUEUED)
        self.assertEqual(len(expired_events), 1)

    def test_recovery_preserves_attempt_until_next_claim(self) -> None:
        with self.runtime() as runtime:
            broker, store, task_id, host_id, first = runtime
            self.expire_lease(broker.database_path, task_id)

            self.reconciler(broker, store).reconcile_once()
            recovered_row = self.request_row(broker.database_path, task_id)
            second = broker.claim_next(host_id, lease_seconds=30)

        self.assertEqual(recovered_row, ("queued", first.attempt_count))
        self.assertEqual(second.attempt_count, first.attempt_count + 1)
        self.assertGreater(second.fencing_token, first.fencing_token)

    def test_attempt_exhaustion_converges_to_dead_letter(self) -> None:
        with self.runtime(max_attempts=2) as runtime:
            broker, store, task_id, host_id, _ = runtime
            self.expire_lease(broker.database_path, task_id)
            reconciler = self.reconciler(broker, store, max_attempts=2)
            reconciler.reconcile_once()
            second = broker.claim_next(host_id, lease_seconds=30)
            store.update_fenced(
                task_id,
                second.fencing_token,
                second.execution_id,
                status=ResearchTaskStatus.RUNNING,
            )
            self.expire_lease(broker.database_path, task_id)

            result = reconciler.reconcile_once()
            status = store.get(task_id).status
            dead_letter_count = len(broker.list_dead_letters())

        self.assertEqual(result.dead_lettered, [task_id])
        self.assertEqual(status, ResearchTaskStatus.DEAD_LETTER)
        self.assertEqual(dead_letter_count, 1)

    def test_old_execution_late_completion_is_rejected_and_new_one_completes(self) -> None:
        with self.runtime() as runtime:
            broker, store, task_id, host_id, first = runtime
            self.expire_lease(broker.database_path, task_id)
            self.reconciler(broker, store).reconcile_once()
            second = broker.claim_next(host_id, lease_seconds=30)
            store.update_fenced(
                task_id,
                second.fencing_token,
                second.execution_id,
                status=ResearchTaskStatus.RUNNING,
            )
            artifact = self.artifact(task_id, second.execution_id)

            stale = store.update_fenced(
                task_id,
                first.fencing_token,
                first.execution_id,
                status=ResearchTaskStatus.COMPLETED,
                artifact=artifact,
                error=None,
            )
            current = store.update_fenced(
                task_id,
                second.fencing_token,
                second.execution_id,
                status=ResearchTaskStatus.COMPLETED,
                artifact=artifact,
                error=None,
            )
            stale_done = broker.mark_done(
                task_id,
                fencing_token=first.fencing_token,
                execution_id=first.execution_id,
            )
            current_done = broker.mark_done(
                task_id,
                fencing_token=second.fencing_token,
                execution_id=second.execution_id,
            )
            final_execution_id = store.get(task_id).artifact.execution_id

        self.assertIsNone(stale)
        self.assertEqual(current.status, ResearchTaskStatus.COMPLETED)
        self.assertFalse(stale_done)
        self.assertTrue(current_done)
        self.assertEqual(final_execution_id, second.execution_id)

    def test_execution_aborted_never_directly_marks_task_failed(self) -> None:
        with self.runtime() as runtime:
            broker, store, task_id, _, lease = runtime

            broker.record_execution_aborted(lease)
            before_recovery = store.get(task_id)
            self.expire_lease(broker.database_path, task_id)
            self.reconciler(broker, store).reconcile_once()
            after_recovery = store.get(task_id)

        self.assertEqual(before_recovery.status, ResearchTaskStatus.RUNNING)
        self.assertEqual(after_recovery.status, ResearchTaskStatus.QUEUED)
        self.assertNotEqual(after_recovery.status, ResearchTaskStatus.FAILED)

    def test_unhealthy_host_cannot_claim_but_fresh_host_can(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            broker = SQLiteHostBroker(path, heartbeat_ttl=1)
            store = PersistentTaskStore(path)
            host_id = uuid4()
            broker.acquire_host(host_id)
            broker.heartbeat(host_id, status=HostStatus.RUNNING)
            task = self.enqueue(store, broker)
            self.make_host_stale(path, host_id)

            rejected = broker.claim_next(host_id, require_healthy_host=True)
            broker.heartbeat(host_id, status=HostStatus.RUNNING)
            accepted = broker.claim_next(host_id, require_healthy_host=True)

        self.assertIsNone(rejected)
        self.assertEqual(accepted.task_id, task.task_id)

    def test_reconciler_survives_one_transient_recovery_failure(self) -> None:
        recovery = FailingOnceRecovery()
        reconciler = RuntimeReconciler(recovery, interval_seconds=0.01)

        reconciler.start()
        self.wait_until(lambda: recovery.calls >= 2)
        reconciler.stop()

        self.assertGreaterEqual(recovery.calls, 2)
        self.assertIsNone(reconciler.last_error_type)
        self.assertFalse(reconciler.is_running)

    def test_task_host_starts_and_stops_reconciler_with_its_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = RuntimeSettings(
                model_name="fake-model",
                llm_provider="fake-provider",
                export_directory=root / "artifacts",
                max_papers=1,
                log_level="ERROR",
            )
            host = TaskHost(
                settings,
                database_path=root / "runtime.sqlite3",
                application_factory=NoopApplicationFactory(),
                poll_interval=0.01,
                lease_seconds=0.3,
                reconciliation_interval=0.02,
            )
            thread = threading.Thread(target=host.serve_forever, daemon=True)

            thread.start()
            self.wait_until(lambda: host.reconciler.is_running)
            host.shutdown()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertFalse(host.reconciler.is_running)

    @staticmethod
    def reconciler(
        broker,
        store,
        *,
        max_attempts: int = 3,
        interval: float = 1,
    ) -> RuntimeReconciler:
        service = RuntimeRecoveryService(
            broker,
            store,
            max_attempts=max_attempts,
        )
        return RuntimeReconciler(service, interval_seconds=interval)

    def runtime(self, *, lease_seconds: float = 30, max_attempts: int = 3):
        del max_attempts
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "runtime.sqlite3"
        broker = SQLiteHostBroker(path, heartbeat_ttl=1)
        store = PersistentTaskStore(path)
        host_id = uuid4()
        broker.acquire_host(host_id)
        broker.heartbeat(host_id, status=HostStatus.RUNNING)
        task = self.enqueue(store, broker)
        lease = broker.claim_next(host_id, lease_seconds=lease_seconds)
        store.update_fenced(
            task.task_id,
            lease.fencing_token,
            lease.execution_id,
            status=ResearchTaskStatus.RUNNING,
        )
        return RuntimeContext(
            temporary,
            broker,
            store,
            task.task_id,
            host_id,
            lease,
        )

    @staticmethod
    def enqueue(store, broker):
        task = store.save(
            ResearchTask(
                run_id=uuid4(),
                question="Reconcile stale runtime task",
                status=ResearchTaskStatus.QUEUED,
            )
        )
        broker.enqueue(task.task_id, ResearchRequest(question=task.question))
        return task

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
    def make_host_stale(path: Path, host_id: UUID) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "UPDATE runtime_host SET heartbeat = ? WHERE host_id = ?",
                (
                    (datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
                    str(host_id),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def request_row(path: Path, task_id: UUID) -> tuple[str, int]:
        connection = sqlite3.connect(path)
        try:
            row = connection.execute(
                "SELECT state, attempt_count FROM task_requests WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
        finally:
            connection.close()
        return row[0], row[1]

    @staticmethod
    def artifact(task_id: UUID, execution_id: str) -> ArtifactMetadata:
        payload = b"current execution artifact"
        return ArtifactMetadata(
            format=ExportFormat.MARKDOWN,
            file_path="report.md",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            task_id=task_id,
            execution_id=execution_id,
        )

    @staticmethod
    def event_types(events):
        return [event.event_type for event in events]

    @staticmethod
    def wait_until(predicate, timeout: float = 2) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        raise AssertionError("condition was not reached before timeout")


class RuntimeContext:
    def __init__(self, temporary, broker, store, task_id, host_id, lease) -> None:
        self.temporary = temporary
        self.value = broker, store, task_id, host_id, lease

    def __enter__(self):
        return self.value

    def __exit__(self, *exc_info) -> None:
        self.temporary.cleanup()


class FailingOnceRecovery:
    def __init__(self) -> None:
        self.calls = 0

    def recover(self):
        self.calls += 1
        if self.calls == 1:
            raise sqlite3.OperationalError("transient store failure")
        return SimpleNamespace(retained=[], requeued=[], dead_lettered=[])


class NoopApplicationService:
    def __init__(self, task_store) -> None:
        self.task_store = task_store

    def run(self, request):
        del request
        raise AssertionError("no task should be dispatched")


class NoopApplicationFactory:
    def __call__(self, config, *, task_store, **kwargs):
        del config, kwargs
        return SimpleNamespace(
            application_service=NoopApplicationService(task_store),
            task_store=task_store,
        )


if __name__ == "__main__":
    unittest.main()
