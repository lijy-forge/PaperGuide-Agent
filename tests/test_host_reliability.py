"""Tests for TaskHost metadata, leases, events, competition, and recovery."""

import os
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from paperguide.application import (
    ResearchRequest,
    ResearchTask,
    ResearchTaskStatus,
)
from paperguide.execution import PersistentTaskStore
from paperguide.runtime.host import (
    HostStatus,
    PersistentTaskHostClient,
    SQLiteHostBroker,
    TaskEventType,
    TaskHostAlreadyRunningError,
)


def make_runtime(directory: str, *, heartbeat_ttl: float = 1.0):
    path = Path(directory) / "runtime.sqlite3"
    return (
        PersistentTaskStore(path),
        SQLiteHostBroker(path, heartbeat_ttl=heartbeat_ttl),
    )


def enqueue_request(store, broker, question="Question"):
    task = store.save(
        ResearchTask(
            run_id=uuid4(),
            question=question,
            status=ResearchTaskStatus.QUEUED,
        )
    )
    broker.enqueue(task.task_id, ResearchRequest(question=question))
    return task


class HostReliabilityTests(unittest.TestCase):
    """Verify host liveness, atomic leases, event history, and crash recovery."""

    def test_heartbeat_updates_structured_host_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, broker = make_runtime(directory)
            host_id = uuid4()
            started_at = datetime.now(UTC)
            initial = broker.acquire_host(
                host_id,
                pid=os.getpid(),
                version="test-version",
                started_at=started_at,
            )
            updated = broker.heartbeat(host_id, status=HostStatus.RUNNING)

            self.assertEqual(initial.host_id, host_id)
            self.assertEqual(initial.pid, os.getpid())
            self.assertEqual(initial.version, "test-version")
            self.assertEqual(initial.status, HostStatus.STARTING)
            self.assertEqual(updated.status, HostStatus.RUNNING)
            self.assertGreaterEqual(updated.heartbeat, initial.heartbeat)
            self.assertTrue(broker.host_available())

            broker.release_host(host_id)
            stopped = broker.get_host_metadata()
            available_after_stop = broker.host_available()

        self.assertEqual(stopped.status, HostStatus.STOPPED)
        self.assertFalse(available_after_stop)

    def test_valid_lease_is_not_claimed_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, broker = make_runtime(directory)
            task = enqueue_request(store, broker)
            first_host = uuid4()
            second_host = uuid4()

            lease = broker.claim_next(first_host, lease_seconds=1)
            duplicate = broker.claim_next(second_host, lease_seconds=1)

        self.assertEqual(lease.task_id, task.task_id)
        self.assertEqual(lease.lease_owner, first_host)
        self.assertEqual(lease.attempt_count, 1)
        self.assertIsNone(duplicate)

    def test_expired_lease_is_recovered_with_incremented_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, broker = make_runtime(directory)
            task = enqueue_request(store, broker)
            first = broker.claim_next(uuid4(), lease_seconds=0.02)
            time.sleep(0.03)
            second_host = uuid4()
            recovered = broker.claim_next(second_host, lease_seconds=1)

        self.assertEqual(first.task_id, task.task_id)
        self.assertEqual(recovered.task_id, task.task_id)
        self.assertEqual(recovered.lease_owner, second_host)
        self.assertEqual(recovered.attempt_count, 2)

    def test_multiple_hosts_compete_for_single_active_metadata_slot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, broker = make_runtime(directory)
            first_host = uuid4()
            second_host = uuid4()
            broker.acquire_host(first_host)
            broker.heartbeat(first_host)

            with self.assertRaises(TaskHostAlreadyRunningError):
                broker.acquire_host(second_host)

            broker.release_host(first_host)
            replacement = broker.acquire_host(second_host)

        self.assertEqual(replacement.host_id, second_host)
        self.assertEqual(replacement.status, HostStatus.STARTING)

    def test_task_event_history_records_content_free_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, broker = make_runtime(directory)
            host_id = uuid4()
            broker.acquire_host(host_id)
            broker.heartbeat(host_id)
            client = PersistentTaskHostClient(store, broker)
            handle = client.submit(ResearchRequest(question="Private paper content"))
            lease = broker.claim_next(host_id, lease_seconds=1)
            broker.record_event(
                handle.task_id,
                TaskEventType.TASK_STARTED,
                ResearchTaskStatus.RUNNING,
                host_id=host_id,
                attempt_count=lease.attempt_count,
            )
            broker.mark_done(
                handle.task_id,
                event_type=TaskEventType.TASK_COMPLETED,
                host_id=host_id,
                status=ResearchTaskStatus.COMPLETED,
                attempt_count=lease.attempt_count,
                duration_ms=12.5,
            )
            events = broker.list_events(handle.task_id)

        self.assertEqual(
            [event.event_type for event in events],
            [
                TaskEventType.TASK_CREATED,
                TaskEventType.TASK_QUEUED,
                TaskEventType.TASK_STARTED,
                TaskEventType.TASK_COMPLETED,
            ],
        )
        self.assertEqual(events[-1].duration_ms, 12.5)
        serialized = " ".join(event.model_dump_json() for event in events)
        self.assertNotIn("Private paper content", serialized)

    def test_stale_host_and_expired_lease_allow_crash_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, broker = make_runtime(directory, heartbeat_ttl=0.02)
            crashed_host = uuid4()
            broker.acquire_host(crashed_host)
            broker.heartbeat(crashed_host)
            task = enqueue_request(store, broker, "Recover task")
            first_lease = broker.claim_next(crashed_host, lease_seconds=0.02)
            store.update(task.task_id, status=ResearchTaskStatus.RUNNING)

            time.sleep(0.03)
            replacement_host = uuid4()
            broker.acquire_host(replacement_host)
            recovered = broker.claim_next(replacement_host, lease_seconds=1)

        self.assertEqual(first_lease.attempt_count, 1)
        self.assertEqual(recovered.task_id, task.task_id)
        self.assertEqual(recovered.lease_owner, replacement_host)
        self.assertEqual(recovered.attempt_count, 2)


if __name__ == "__main__":
    unittest.main()
