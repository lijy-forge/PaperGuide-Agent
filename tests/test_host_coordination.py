"""Production coordination tests for schema, fences, events, and metrics."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from paperguide.application import (
    ResearchRequest,
    ResearchTask,
    ResearchTaskStatus,
)
from paperguide.execution import PersistentTaskStore
from paperguide.runtime.host import (
    CURRENT_SCHEMA_VERSION,
    RuntimeMetrics,
    SQLiteHostBroker,
    TaskEventType,
)


class HostCoordinationTests(unittest.TestCase):
    """Verify production-safe SQLite host coordination primitives."""

    def test_legacy_schema_is_migrated_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    """
                    CREATE TABLE task_requests (
                        task_id TEXT PRIMARY KEY,
                        request_json TEXT NOT NULL,
                        state TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            broker = SQLiteHostBroker(path)
            current_version = broker.schema_version()
            connection = sqlite3.connect(path)
            try:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(task_requests)"
                    )
                }
                versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_version ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertEqual(current_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(
            versions,
            list(range(1, CURRENT_SCHEMA_VERSION + 1)),
        )
        self.assertIn("fencing_token", columns)
        self.assertIn("execution_id", columns)

    def test_each_recovered_lease_gets_a_new_fencing_token(self) -> None:
        with self.coordination() as context:
            broker, _, task_id = context
            first = broker.claim_next(uuid4(), lease_seconds=30)
            self.assertIsNotNone(first)
            self.expire_lease(broker.database_path, task_id)
            second = broker.claim_next(uuid4(), lease_seconds=30)

        self.assertIsNotNone(second)
        self.assertGreater(second.fencing_token, first.fencing_token)
        self.assertEqual(second.attempt_count, first.attempt_count + 1)

    def test_stale_worker_cannot_update_or_finalize_new_attempt(self) -> None:
        with self.coordination() as context:
            broker, store, task_id = context
            first = broker.claim_next(uuid4(), lease_seconds=30)
            self.expire_lease(broker.database_path, task_id)
            second = broker.claim_next(uuid4(), lease_seconds=30)

            stale_update = store.update_fenced(
                task_id,
                first.fencing_token,
                first.execution_id,
                status=ResearchTaskStatus.FAILED,
                artifact=None,
                error="stale result",
            )
            stale_finalize = broker.mark_done(
                task_id,
                fencing_token=first.fencing_token,
                execution_id=first.execution_id,
            )
            current_update = store.update_fenced(
                task_id,
                second.fencing_token,
                second.execution_id,
                status=ResearchTaskStatus.RUNNING,
            )

        self.assertIsNone(stale_update)
        self.assertFalse(stale_finalize)
        self.assertEqual(current_update.status, ResearchTaskStatus.RUNNING)

    def test_execution_id_is_stable_for_task_attempt(self) -> None:
        with self.coordination() as context:
            broker, _, task_id = context
            first = broker.claim_next(uuid4(), lease_seconds=30)
            self.expire_lease(broker.database_path, task_id)
            second = broker.claim_next(uuid4(), lease_seconds=30)

        self.assertEqual(first.execution_id, f"{task_id}:1")
        self.assertEqual(second.execution_id, f"{task_id}:2")
        self.assertNotEqual(first.execution_id, second.execution_id)

    def test_event_query_supports_limit_and_offset(self) -> None:
        with self.coordination() as context:
            broker, _, task_id = context
            event_types = [
                TaskEventType.TASK_CREATED,
                TaskEventType.TASK_QUEUED,
                TaskEventType.TASK_STARTED,
                TaskEventType.TASK_COMPLETED,
            ]
            for event_type in event_types:
                broker.record_event(
                    task_id,
                    event_type,
                    self.status_for(event_type),
                )
            page = broker.list_events(task_id, limit=2, offset=1)

        self.assertEqual(
            [event.event_type for event in page],
            event_types[1:3],
        )

    def test_runtime_metrics_report_queue_workers_and_terminals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.sqlite3"
            broker = SQLiteHostBroker(path)
            task_ids = [uuid4() for _ in range(3)]
            for task_id in task_ids:
                broker.enqueue(task_id, ResearchRequest(question="Metrics"))
            completed = broker.claim_next(uuid4())
            broker.mark_done(
                completed.task_id,
                event_type=TaskEventType.TASK_COMPLETED,
                status=ResearchTaskStatus.COMPLETED,
                fencing_token=completed.fencing_token,
                execution_id=completed.execution_id,
            )
            broker.claim_next(uuid4())
            broker.record_event(
                task_ids[1],
                TaskEventType.TASK_FAILED,
                ResearchTaskStatus.FAILED,
            )
            broker.record_event(
                task_ids[2],
                TaskEventType.TASK_CANCELLED,
                ResearchTaskStatus.CANCELLED,
            )
            metrics = broker.get_metrics()

        self.assertIsInstance(metrics, RuntimeMetrics)
        self.assertEqual(metrics.submitted, 3)
        self.assertEqual(metrics.completed, 1)
        self.assertEqual(metrics.failed, 1)
        self.assertEqual(metrics.cancelled, 1)
        self.assertEqual(metrics.active_workers, 1)
        self.assertEqual(metrics.queue_size, 1)

    def coordination(self):
        """Create one persisted queued task and its broker."""

        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "coordination.sqlite3"
        store = PersistentTaskStore(path)
        broker = SQLiteHostBroker(path)
        task = store.save(
            ResearchTask(run_id=uuid4(), question="Coordinate this paper")
        )
        store.update(task.task_id, status=ResearchTaskStatus.QUEUED)
        broker.enqueue(task.task_id, ResearchRequest(question=task.question))
        return _CoordinationContext(temporary, broker, store, task.task_id)

    @staticmethod
    def expire_lease(path: Path, task_id) -> None:
        expired = datetime.now(timezone.utc) - timedelta(seconds=1)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "UPDATE task_requests SET lease_until = ? WHERE task_id = ?",
                (expired.isoformat(), str(task_id)),
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def status_for(event_type: TaskEventType) -> ResearchTaskStatus:
        return {
            TaskEventType.TASK_CREATED: ResearchTaskStatus.CREATED,
            TaskEventType.TASK_QUEUED: ResearchTaskStatus.QUEUED,
            TaskEventType.TASK_STARTED: ResearchTaskStatus.RUNNING,
            TaskEventType.TASK_COMPLETED: ResearchTaskStatus.COMPLETED,
        }[event_type]


class _CoordinationContext:
    def __init__(self, temporary, broker, store, task_id) -> None:
        self.temporary = temporary
        self.value = broker, store, task_id

    def __enter__(self):
        return self.value

    def __exit__(self, *exc_info) -> None:
        self.temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
