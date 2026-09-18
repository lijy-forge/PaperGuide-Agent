"""SQLite command queue and heartbeat used for local cross-process coordination."""

import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from paperguide.application import ResearchRequest, ResearchTaskStatus
from paperguide.progress.models import ProgressEventPayload

from .exceptions import TaskHostAlreadyRunningError
from .models import (
    DeadLetterTask,
    HostStatus,
    LeaseLossReason,
    LeaseRenewalResult,
    RuntimeHostMetadata,
    RuntimeMetrics,
    RuntimeRecoveryResult,
    TaskEvent,
    TaskEventType,
    TaskLease,
)
from .preflight import ProviderPreflightResult
from .schema import get_schema_version, migrate_schema


class SQLiteHostBroker:
    """Coordinate one host and many CLI clients through a local SQLite file."""

    def __init__(self, database_path: str | Path, *, heartbeat_ttl: float = 5.0):
        if heartbeat_ttl <= 0:
            raise ValueError("heartbeat_ttl must be positive")
        self.database_path = Path(database_path)
        self.heartbeat_ttl = heartbeat_ttl
        self._lock = RLock()
        self._initialize()

    def acquire_host(
        self,
        host_id: UUID,
        *,
        pid: int | None = None,
        version: str = "paperguide-10.14",
        started_at: datetime | None = None,
    ) -> RuntimeHostMetadata:
        now = datetime.now(UTC)
        resolved_started_at = started_at or now
        resolved_pid = pid or os.getpid()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT host_id, heartbeat, status
                FROM runtime_host WHERE singleton = 1
                """
            ).fetchone()
            if (
                row is not None
                and row[0] != str(host_id)
                and row[2] in (HostStatus.STARTING.value, HostStatus.RUNNING.value)
            ):
                heartbeat = datetime.fromisoformat(row[1])
                if now - heartbeat <= timedelta(seconds=self.heartbeat_ttl):
                    raise TaskHostAlreadyRunningError(
                        "another persistent task host is already running"
                    )
            connection.execute(
                """
                INSERT INTO runtime_host(
                    singleton, host_id, pid, version, started_at, heartbeat, status
                )
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    host_id = excluded.host_id,
                    pid = excluded.pid,
                    version = excluded.version,
                    started_at = excluded.started_at,
                    heartbeat = excluded.heartbeat,
                    status = excluded.status
                """,
                (
                    str(host_id),
                    resolved_pid,
                    version,
                    resolved_started_at.isoformat(),
                    now.isoformat(),
                    HostStatus.STARTING.value,
                ),
            )
        return self.get_host_metadata()

    def heartbeat(
        self,
        host_id: UUID,
        *,
        status: HostStatus = HostStatus.RUNNING,
    ) -> RuntimeHostMetadata:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE runtime_host SET heartbeat = ?, status = ?
                WHERE singleton = 1 AND host_id = ?
                """,
                (
                    datetime.now(UTC).isoformat(),
                    status.value,
                    str(host_id),
                ),
            )
            if cursor.rowcount != 1:
                raise TaskHostAlreadyRunningError("task host ownership was lost")
        return self.get_host_metadata()

    def release_host(
        self,
        host_id: UUID,
        *,
        status: HostStatus = HostStatus.STOPPED,
    ) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE runtime_host SET heartbeat = ?, status = ?
                WHERE singleton = 1 AND host_id = ?
                """,
                (
                    datetime.now(UTC).isoformat(),
                    status.value,
                    str(host_id),
                ),
            )

    def set_host_status(self, host_id: UUID, status: HostStatus) -> None:
        self.heartbeat(host_id, status=status)

    def get_host_metadata(self) -> RuntimeHostMetadata:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT host_id, pid, version, started_at, heartbeat, status
                FROM runtime_host WHERE singleton = 1
                """
            ).fetchone()
        if row is None:
            raise TaskHostAlreadyRunningError("runtime host metadata is unavailable")
        return RuntimeHostMetadata(
            host_id=UUID(row[0]),
            pid=row[1],
            version=row[2],
            started_at=datetime.fromisoformat(row[3]),
            heartbeat=datetime.fromisoformat(row[4]),
            status=HostStatus(row[5]),
        )

    def host_available(self) -> bool:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT heartbeat, status FROM runtime_host WHERE singleton = 1
                """
            ).fetchone()
        if row is None:
            return False
        try:
            heartbeat = datetime.fromisoformat(row[0])
        except (TypeError, ValueError):
            return False
        if row[1] not in (HostStatus.STARTING.value, HostStatus.RUNNING.value):
            return False
        return datetime.now(UTC) - heartbeat <= timedelta(
            seconds=self.heartbeat_ttl
        )

    def enqueue_provider_preflight(self) -> UUID:
        """Queue one explicit, private Host-context provider preflight."""

        request_id = uuid4()
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO provider_preflight_requests(
                    request_id, state, created_at, updated_at, result_json
                ) VALUES (?, 'queued', ?, ?, NULL)
                """,
                (str(request_id), now, now),
            )
        return request_id

    def claim_provider_preflight(self, host_id: UUID) -> UUID | None:
        """Atomically claim the oldest preflight command for its owning Host."""

        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            host = connection.execute(
                """
                SELECT host_id, status FROM runtime_host WHERE singleton = 1
                """
            ).fetchone()
            if (
                host is None
                or host[0] != str(host_id)
                or host[1] != HostStatus.RUNNING.value
            ):
                return None
            row = connection.execute(
                """
                SELECT request_id FROM provider_preflight_requests
                WHERE state = 'queued' ORDER BY created_at LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            cursor = connection.execute(
                """
                UPDATE provider_preflight_requests
                SET state = 'running', updated_at = ?
                WHERE request_id = ? AND state = 'queued'
                """,
                (datetime.now(UTC).isoformat(), row[0]),
            )
            return UUID(row[0]) if cursor.rowcount == 1 else None

    def complete_provider_preflight(
        self,
        request_id: UUID,
        result: ProviderPreflightResult,
    ) -> bool:
        """Persist the sanitized result; raw provider data is never stored."""

        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE provider_preflight_requests
                SET state = 'done', updated_at = ?, result_json = ?
                WHERE request_id = ? AND state = 'running'
                """,
                (
                    datetime.now(UTC).isoformat(),
                    result.model_dump_json(),
                    str(request_id),
                ),
            )
        return cursor.rowcount == 1

    def get_provider_preflight(self, request_id: UUID) -> ProviderPreflightResult | None:
        """Return a completed safe preflight result, if available."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT state, result_json FROM provider_preflight_requests
                WHERE request_id = ?
                """,
                (str(request_id),),
            ).fetchone()
        if row is None or row[0] != "done" or row[1] is None:
            return None
        return ProviderPreflightResult.model_validate_json(row[1])

    def wait_provider_preflight(
        self,
        request_id: UUID,
        *,
        timeout_seconds: float,
        poll_interval: float = 0.05,
    ) -> ProviderPreflightResult | None:
        """Wait a bounded time for the active Host to finish one command."""

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result = self.get_provider_preflight(request_id)
            if result is not None:
                return result
            time.sleep(poll_interval)
        return self.get_provider_preflight(request_id)

    def enqueue(self, task_id: UUID, request: ResearchRequest) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO task_requests(task_id, request_json, state, created_at)
                VALUES (?, ?, 'queued', ?)
                """,
                (
                    str(task_id),
                    request.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def claim_next(
        self,
        host_id: UUID,
        *,
        lease_seconds: float = 30.0,
        require_healthy_host: bool = False,
    ) -> TaskLease | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if require_healthy_host and not self._host_is_healthy(
                connection,
                host_id,
                now,
            ):
                return None
            row = connection.execute(
                """
                SELECT task_id, request_json, attempt_count, fencing_token
                FROM task_requests
                WHERE
                    state = 'queued'
                    OR (
                        state = 'dispatched'
                        AND lease_until IS NOT NULL
                        AND lease_until <= ?
                    )
                ORDER BY created_at ASC, task_id ASC
                LIMIT 1
                """,
                (now.isoformat(),),
            ).fetchone()
            if row is None:
                return None
            next_attempt = row[2] + 1
            next_token = row[3] + 1
            execution_id = f"{row[0]}:{next_attempt}"
            cursor = connection.execute(
                """
                UPDATE task_requests SET
                    state = 'dispatched',
                    lease_owner = ?,
                    lease_until = ?,
                    attempt_count = ?,
                    fencing_token = ?,
                    execution_id = ?
                WHERE task_id = ? AND (
                    state = 'queued'
                    OR (
                        state = 'dispatched'
                        AND lease_until IS NOT NULL
                        AND lease_until <= ?
                    )
                )
                """,
                (
                    str(host_id),
                    lease_until.isoformat(),
                    next_attempt,
                    next_token,
                    execution_id,
                    row[0],
                    now.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                return None
        return TaskLease(
            task_id=UUID(row[0]),
            request=ResearchRequest.model_validate_json(row[1]),
            lease_owner=host_id,
            lease_until=lease_until,
            attempt_count=next_attempt,
            fencing_token=next_token,
            execution_id=execution_id,
        )

    def _host_is_healthy(
        self,
        connection: sqlite3.Connection,
        host_id: UUID,
        now: datetime,
    ) -> bool:
        row = connection.execute(
            """
            SELECT host_id, heartbeat, status FROM runtime_host
            WHERE singleton = 1
            """
        ).fetchone()
        return bool(
            row is not None
            and row[0] == str(host_id)
            and row[2] == HostStatus.RUNNING.value
            and now - datetime.fromisoformat(row[1])
            <= timedelta(seconds=self.heartbeat_ttl)
        )

    def renew_leases(self, host_id: UUID, *, lease_seconds: float = 30.0) -> int:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        lease_until = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE task_requests SET lease_until = ?
                WHERE state = 'dispatched' AND lease_owner = ?
                """,
                (lease_until.isoformat(), str(host_id)),
            )
            return cursor.rowcount

    def renew_task_lease(
        self,
        task_id: UUID,
        host_id: UUID,
        fencing_token: int,
        *,
        lease_seconds: float = 30.0,
    ) -> LeaseRenewalResult:
        """Validate and renew one worker lease without reviving an expired lease."""

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT state, lease_owner, lease_until, fencing_token,
                       attempt_count
                FROM task_requests WHERE task_id = ?
                """,
                (str(task_id),),
            ).fetchone()
            reason = self._lease_loss_reason(
                connection,
                row,
                host_id,
                fencing_token,
                now,
            )
            if reason is not None:
                if reason is LeaseLossReason.EXPIRED and row is not None:
                    self._insert_event_once(
                        connection,
                        task_id=task_id,
                        event_type=TaskEventType.LEASE_EXPIRED,
                        host_id=host_id,
                        status=ResearchTaskStatus.RUNNING,
                        attempt_count=row[4],
                    )
                return LeaseRenewalResult(
                    renewed=False,
                    loss_reason=reason,
                )
            connection.execute(
                """
                UPDATE task_requests SET lease_until = ?
                WHERE task_id = ? AND lease_owner = ? AND fencing_token = ?
                """,
                (
                    lease_until.isoformat(),
                    str(task_id),
                    str(host_id),
                    fencing_token,
                ),
            )
            self._insert_event(
                connection,
                task_id=task_id,
                event_type=TaskEventType.LEASE_RENEWED,
                host_id=host_id,
                status=ResearchTaskStatus.RUNNING,
                attempt_count=row[4],
                duration_ms=None,
            )
        return LeaseRenewalResult(renewed=True, lease_until=lease_until)

    def record_execution_aborted(
        self,
        lease: TaskLease,
    ) -> None:
        """Record one content-free cooperative abort event idempotently."""

        with self._lock, self._connection() as connection:
            self._insert_event_once(
                connection,
                task_id=lease.task_id,
                event_type=TaskEventType.EXECUTION_ABORTED,
                host_id=lease.lease_owner,
                status=ResearchTaskStatus.RUNNING,
                attempt_count=lease.attempt_count,
            )

    def mark_done(
        self,
        task_id: UUID,
        *,
        event_type: TaskEventType | None = None,
        host_id: UUID | None = None,
        status: ResearchTaskStatus | None = None,
        attempt_count: int = 0,
        duration_ms: float | None = None,
        fencing_token: int | None = None,
        execution_id: str | None = None,
    ) -> bool:
        if (fencing_token is None) != (execution_id is None):
            raise ValueError(
                "fencing_token and execution_id must be provided together"
            )
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            query = """
                UPDATE task_requests SET
                    state = 'done', lease_owner = NULL, lease_until = NULL
                WHERE task_id = ? AND state != 'done'
            """
            parameters: tuple[object, ...] = (str(task_id),)
            if fencing_token is not None:
                query += " AND fencing_token = ? AND execution_id = ?"
                parameters += (fencing_token, execution_id)
            cursor = connection.execute(query, parameters)
            changed = cursor.rowcount == 1
            if changed and event_type is not None and status is not None:
                self._insert_event(
                    connection,
                    task_id=task_id,
                    event_type=event_type,
                    host_id=host_id,
                    status=status,
                    attempt_count=attempt_count,
                    duration_ms=duration_ms,
                )
            elif (
                not changed
                and fencing_token is not None
                and status is not None
            ):
                self._insert_event_once(
                    connection,
                    task_id=task_id,
                    event_type=TaskEventType.STALE_WORKER_REJECTED,
                    host_id=host_id,
                    status=status,
                    attempt_count=attempt_count,
                )
            return changed

    def move_to_dead_letter(
        self,
        task_id: UUID,
        *,
        execution_id: str,
        last_status: str,
        last_error_type: str,
        failed_stage: str,
        attempt_count: int,
        fencing_token: int | None = None,
        host_id: UUID | None = None,
    ) -> bool:
        """Atomically stop a task and persist one idempotent dead-letter record."""

        record = DeadLetterTask(
            task_id=task_id,
            execution_id=execution_id,
            last_status=last_status,
            last_error_type=last_error_type,
            failed_stage=failed_stage,
            attempt_count=attempt_count,
            created_at=datetime.now(UTC),
        )
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            query = """
                UPDATE task_requests SET
                    state = 'done', lease_owner = NULL, lease_until = NULL
                WHERE task_id = ? AND state != 'done'
            """
            parameters: tuple[object, ...] = (str(task_id),)
            if fencing_token is not None:
                query += " AND fencing_token = ? AND execution_id = ?"
                parameters += (fencing_token, execution_id)
            changed = connection.execute(query, parameters).rowcount == 1
            if not changed:
                return False
            connection.execute(
                """
                INSERT INTO dead_letter_tasks(
                    id, task_id, execution_id, last_status, last_error_type,
                    failed_stage, attempt_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO NOTHING
                """,
                (
                    str(record.id),
                    str(record.task_id),
                    record.execution_id,
                    record.last_status,
                    record.last_error_type,
                    record.failed_stage,
                    record.attempt_count,
                    record.created_at.isoformat(),
                ),
            )
            self._insert_event_once(
                connection,
                task_id=task_id,
                event_type=TaskEventType.TASK_DEAD_LETTER,
                host_id=host_id,
                status=ResearchTaskStatus.DEAD_LETTER,
                attempt_count=attempt_count,
            )
        return True

    def list_dead_letters(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DeadLetterTask]:
        """Return content-free dead letters in deterministic creation order."""

        if limit < 1:
            raise ValueError("limit must be at least one")
        if offset < 0:
            raise ValueError("offset must not be negative")
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, task_id, execution_id, last_status, last_error_type,
                       failed_stage, attempt_count, created_at
                FROM dead_letter_tasks
                ORDER BY created_at ASC, task_id ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._dead_letter_from_row(row) for row in rows]

    def recover_incomplete(self, *, max_attempts: int) -> RuntimeRecoveryResult:
        """Idempotently retain, requeue, or dead-letter dispatched requests."""

        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        now = datetime.now(UTC)
        retained: list[UUID] = []
        requeued: list[UUID] = []
        dead_lettered: list[UUID] = []
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT task_id, lease_until, attempt_count, execution_id
                FROM task_requests WHERE state = 'dispatched'
                ORDER BY created_at ASC, task_id ASC
                """
            ).fetchall()
            for row in rows:
                task_id = UUID(row[0])
                if row[1] is not None and datetime.fromisoformat(row[1]) > now:
                    retained.append(task_id)
                    continue
                if row[2] >= max_attempts:
                    self._dead_letter_recovery_row(connection, row, now)
                    dead_lettered.append(task_id)
                    continue
                connection.execute(
                    """
                    UPDATE task_requests SET
                        state = 'queued', lease_owner = NULL, lease_until = NULL
                    WHERE task_id = ? AND state = 'dispatched'
                    """,
                    (row[0],),
                )
                self._insert_event_once(
                    connection,
                    task_id=task_id,
                    event_type=TaskEventType.LEASE_EXPIRED,
                    host_id=None,
                    status=ResearchTaskStatus.RUNNING,
                    attempt_count=row[2],
                )
                requeued.append(task_id)
        return RuntimeRecoveryResult(
            retained=retained,
            requeued=requeued,
            dead_lettered=dead_lettered,
        )

    def requeue_dispatched(self) -> list[UUID]:
        """Requeue only requests whose lease has expired."""

        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT task_id FROM task_requests
                WHERE state = 'dispatched' AND lease_until <= ?
                """,
                (now,),
            ).fetchall()
            connection.execute(
                """
                UPDATE task_requests SET
                    state = 'queued', lease_owner = NULL, lease_until = NULL
                WHERE state = 'dispatched' AND lease_until <= ?
                """,
                (now,),
            )
        return [UUID(row[0]) for row in rows]

    def record_event(
        self,
        task_id: UUID,
        event_type: TaskEventType,
        status: ResearchTaskStatus,
        *,
        host_id: UUID | None = None,
        attempt_count: int = 0,
        duration_ms: float | None = None,
    ) -> TaskEvent:
        with self._lock, self._connection() as connection:
            event_id = self._insert_event(
                connection,
                task_id=task_id,
                event_type=event_type,
                host_id=host_id,
                status=status,
                attempt_count=attempt_count,
                duration_ms=duration_ms,
            )
            row = self._select_event(connection, event_id)
        return self._event_from_row(row)

    def record_progress_event(
        self,
        task_id: UUID,
        event_type: TaskEventType,
        status: ResearchTaskStatus,
        progress: ProgressEventPayload,
        *,
        dedupe_key: str,
    ) -> TaskEvent | None:
        """Append one validated public progress event, idempotently."""

        with self._lock, self._connection() as connection:
            event_id = self._insert_event(
                connection,
                task_id=task_id,
                event_type=event_type,
                host_id=None,
                status=status,
                attempt_count=0,
                duration_ms=progress.elapsed_ms,
                progress=progress,
                dedupe_key=dedupe_key,
                ignore_duplicate=True,
            )
            if event_id is None:
                return None
            row = self._select_event(connection, event_id)
        return self._event_from_row(row)

    def list_events(
        self,
        task_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
        after_id: int | None = None,
        event_type: TaskEventType | None = None,
    ) -> list[TaskEvent]:
        if limit < 1:
            raise ValueError("limit must be at least one")
        if offset < 0:
            raise ValueError("offset must not be negative")
        if after_id is not None and after_id < 0:
            raise ValueError("after_id must not be negative")
        with self._lock, self._connection() as connection:
            where = "task_id = ?"
            parameters: list[object] = [str(task_id)]
            if event_type is not None:
                where += " AND event_type = ?"
                parameters.append(event_type.value)
            if after_id is not None:
                where += " AND event_id > ?"
                parameters.append(after_id)
            parameters.extend((limit, offset))
            rows = connection.execute(
                f"""
                SELECT event_id, task_id, event_type, host_id, status,
                       attempt_count, duration_ms, created_at, progress_json
                FROM task_events WHERE {where} AND diagnostic_json IS NULL
                ORDER BY event_id ASC
                LIMIT ? OFFSET ?
                """,
                tuple(parameters),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def record_diagnostic_event(
        self,
        task_id: UUID,
        event_type: TaskEventType,
        status: ResearchTaskStatus,
        payload: dict[str, object],
        *,
        attempt_count: int = 0,
        duration_ms: float | None = None,
        dedupe_key: str | None = None,
    ) -> int | None:
        """Persist a private, scalar-only diagnostic event.

        ``diagnostic_json`` is intentionally excluded from ``list_events`` and
        therefore from the public API projection.
        """

        from paperguide.progress.diagnostics import safe_diagnostic_payload

        safe = safe_diagnostic_payload(payload)
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO task_events(
                    task_id, event_type, host_id, status, attempt_count,
                    duration_ms, created_at, progress_json, dedupe_key,
                    diagnostic_json
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    str(task_id),
                    event_type.value,
                    status.value,
                    attempt_count,
                    duration_ms,
                    datetime.now(UTC).isoformat(),
                    dedupe_key,
                    json.dumps(safe, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            return int(cursor.lastrowid) if cursor.rowcount else None

    def list_diagnostic_events(
        self,
        task_id: UUID,
        *,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        """Read private diagnostics for internal evaluation tooling only."""

        if limit < 1 or offset < 0:
            raise ValueError("invalid diagnostic event paging")
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, status, attempt_count,
                       duration_ms, created_at, diagnostic_json
                FROM task_events
                WHERE task_id = ? AND diagnostic_json IS NOT NULL
                ORDER BY event_id ASC LIMIT ? OFFSET ?
                """,
                (str(task_id), limit, offset),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            payload = json.loads(row[6]) if row[6] else {}
            result.append(
                {
                    "event_id": row[0],
                    "event_type": row[1],
                    "status": row[2],
                    "attempt_count": row[3],
                    "duration_ms": row[4],
                    "created_at": row[5],
                    "diagnostic": payload,
                }
            )
        return result

    def get_metrics(self) -> RuntimeMetrics:
        """Return an atomic point-in-time runtime metrics snapshot."""

        with self._lock, self._connection() as connection:
            submitted = connection.execute(
                "SELECT COUNT(*) FROM task_requests"
            ).fetchone()[0]
            states = dict(
                connection.execute(
                    "SELECT state, COUNT(*) FROM task_requests GROUP BY state"
                ).fetchall()
            )
            active_workers = connection.execute(
                "SELECT COUNT(DISTINCT lease_owner) FROM task_requests "
                "WHERE state = 'dispatched' AND lease_owner IS NOT NULL"
            ).fetchone()[0]
            event_counts = dict(
                connection.execute(
                    """
                    SELECT event_type, COUNT(*) FROM task_events
                    WHERE event_type IN (?, ?, ?, ?, ?, ?)
                    GROUP BY event_type
                    """,
                    (
                        TaskEventType.TASK_COMPLETED.value,
                        TaskEventType.TASK_FAILED.value,
                        TaskEventType.TASK_CANCELLED.value,
                        TaskEventType.TASK_DEAD_LETTER.value,
                        TaskEventType.LEASE_EXPIRED.value,
                        TaskEventType.STALE_WORKER_REJECTED.value,
                    ),
                ).fetchall()
            )
            duration = connection.execute(
                """
                SELECT COALESCE(AVG(duration_ms), 0.0) FROM task_events
                WHERE duration_ms IS NOT NULL AND event_type IN (?, ?)
                """,
                (
                    TaskEventType.TASK_COMPLETED.value,
                    TaskEventType.TASK_FAILED.value,
                ),
            ).fetchone()[0]
        return RuntimeMetrics(
            submitted=submitted,
            completed=event_counts.get(TaskEventType.TASK_COMPLETED.value, 0),
            failed=event_counts.get(TaskEventType.TASK_FAILED.value, 0),
            cancelled=event_counts.get(TaskEventType.TASK_CANCELLED.value, 0),
            # Distinct lease holders, not dispatched rows: one worker can hold
            # several tasks, so counting rows made this identical to
            # running_tasks and the dashboard showed the same number twice.
            active_workers=active_workers,
            queue_size=states.get("queued", 0),
            running_tasks=states.get("dispatched", 0),
            dead_letter_total=event_counts.get(
                TaskEventType.TASK_DEAD_LETTER.value,
                0,
            ),
            lease_expired_total=event_counts.get(
                TaskEventType.LEASE_EXPIRED.value,
                0,
            ),
            stale_worker_rejected_total=event_counts.get(
                TaskEventType.STALE_WORKER_REJECTED.value,
                0,
            ),
            average_execution_time_ms=float(duration),
        )

    def schema_version(self) -> int:
        """Return the runtime database schema version checked at startup."""

        with self._lock, self._connection() as connection:
            return get_schema_version(connection)

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            migrate_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=10,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        task_id: UUID,
        event_type: TaskEventType,
        host_id: UUID | None,
        status: ResearchTaskStatus,
        attempt_count: int,
        duration_ms: float | None,
        progress: ProgressEventPayload | None = None,
        dedupe_key: str | None = None,
        ignore_duplicate: bool = False,
    ) -> int | None:
        clause = "OR IGNORE " if ignore_duplicate else ""
        cursor = connection.execute(
            f"""
            INSERT {clause}INTO task_events(
                task_id, event_type, host_id, status,
                attempt_count, duration_ms, created_at, progress_json, dedupe_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(task_id),
                event_type.value,
                str(host_id) if host_id is not None else None,
                status.value,
                attempt_count,
                duration_ms,
                datetime.now(UTC).isoformat(),
                progress.model_dump_json() if progress is not None else None,
                dedupe_key,
            ),
        )
        return int(cursor.lastrowid) if cursor.rowcount else None

    @staticmethod
    def _event_from_row(row) -> TaskEvent:
        return TaskEvent(
            event_id=row[0],
            task_id=UUID(row[1]),
            event_type=TaskEventType(row[2]),
            host_id=UUID(row[3]) if row[3] is not None else None,
            status=ResearchTaskStatus(row[4]),
            attempt_count=row[5],
            duration_ms=row[6],
            created_at=datetime.fromisoformat(row[7]),
            progress=(
                ProgressEventPayload.model_validate_json(row[8])
                if len(row) > 8 and row[8] is not None
                else None
            ),
        )

    @staticmethod
    def _select_event(connection: sqlite3.Connection, event_id: int):
        return connection.execute(
            """
            SELECT event_id, task_id, event_type, host_id, status,
                   attempt_count, duration_ms, created_at, progress_json
            FROM task_events WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()

    def _lease_loss_reason(
        self,
        connection: sqlite3.Connection,
        row,
        host_id: UUID,
        fencing_token: int,
        now: datetime,
    ) -> LeaseLossReason | None:
        if row is None or row[0] != "dispatched":
            return LeaseLossReason.TASK_UNAVAILABLE
        if row[3] != fencing_token:
            return LeaseLossReason.FENCING_TOKEN_CHANGED
        host = connection.execute(
            """
            SELECT host_id, heartbeat, status FROM runtime_host
            WHERE singleton = 1
            """
        ).fetchone()
        if (
            row[1] != str(host_id)
            or host is None
            or host[0] != str(host_id)
            or host[2] != HostStatus.RUNNING.value
            or now - datetime.fromisoformat(host[1])
            > timedelta(seconds=self.heartbeat_ttl)
        ):
            return LeaseLossReason.HOST_OWNERSHIP_LOST
        if row[2] is None or datetime.fromisoformat(row[2]) <= now:
            return LeaseLossReason.EXPIRED
        return None

    @staticmethod
    def _dead_letter_from_row(row) -> DeadLetterTask:
        return DeadLetterTask(
            id=UUID(row[0]),
            task_id=UUID(row[1]),
            execution_id=row[2],
            last_status=row[3],
            last_error_type=row[4],
            failed_stage=row[5],
            attempt_count=row[6],
            created_at=datetime.fromisoformat(row[7]),
        )

    def _dead_letter_recovery_row(
        self,
        connection: sqlite3.Connection,
        row,
        now: datetime,
    ) -> None:
        task_id = UUID(row[0])
        execution_id = row[3] or f"{task_id}:{row[2]}"
        record = DeadLetterTask(
            task_id=task_id,
            execution_id=execution_id,
            last_status=ResearchTaskStatus.FAILED.value,
            last_error_type="RetryLimitExceeded",
            failed_stage="execution",
            attempt_count=row[2],
            created_at=now,
        )
        connection.execute(
            """
            UPDATE task_requests SET
                state = 'done', lease_owner = NULL, lease_until = NULL
            WHERE task_id = ? AND state = 'dispatched'
            """,
            (row[0],),
        )
        connection.execute(
            """
            INSERT INTO dead_letter_tasks(
                id, task_id, execution_id, last_status, last_error_type,
                failed_stage, attempt_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO NOTHING
            """,
            (
                str(record.id),
                str(record.task_id),
                record.execution_id,
                record.last_status,
                record.last_error_type,
                record.failed_stage,
                record.attempt_count,
                record.created_at.isoformat(),
            ),
        )
        self._insert_event_once(
            connection,
            task_id=task_id,
            event_type=TaskEventType.TASK_DEAD_LETTER,
            host_id=None,
            status=ResearchTaskStatus.DEAD_LETTER,
            attempt_count=row[2],
        )

    def _insert_event_once(
        self,
        connection: sqlite3.Connection,
        *,
        task_id: UUID,
        event_type: TaskEventType,
        host_id: UUID | None,
        status: ResearchTaskStatus,
        attempt_count: int,
    ) -> int | None:
        existing = connection.execute(
            """
            SELECT event_id FROM task_events
            WHERE task_id = ? AND event_type = ? AND attempt_count = ?
            LIMIT 1
            """,
            (str(task_id), event_type.value, attempt_count),
        ).fetchone()
        if existing is not None:
            return None
        return self._insert_event(
            connection,
            task_id=task_id,
            event_type=event_type,
            host_id=host_id,
            status=status,
            attempt_count=attempt_count,
            duration_ms=None,
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
