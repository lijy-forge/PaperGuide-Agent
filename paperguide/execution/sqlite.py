"""SQLite-backed persistent implementation of the application TaskStore protocol."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import UUID

from paperguide.application import ResearchTask, TaskNotFoundError

from .exceptions import TaskExecutionError


class PersistentTaskStoreError(TaskExecutionError):
    """Raised when persistent task state cannot be read or written."""


class PersistentTaskStore:
    """Persist ResearchTask JSON in a thread-safe local SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def save(self, task: ResearchTask) -> ResearchTask:
        """Insert or replace one validated task snapshot."""

        stored = ResearchTask.model_validate(task.model_dump())
        payload = stored.model_dump_json()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO research_tasks(task_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    payload = excluded.payload,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    str(stored.task_id),
                    payload,
                    stored.created_at.isoformat(),
                    stored.updated_at.isoformat(),
                ),
            )
        return deepcopy(stored)

    def get(self, task_id: UUID) -> ResearchTask:
        """Load one isolated task or raise TaskNotFoundError."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM research_tasks WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"research task not found: {task_id}")
        return deepcopy(self._parse_task(row[0]))

    def update(self, task_id: UUID, **changes: object) -> ResearchTask:
        """Atomically validate and update supported task lifecycle fields."""

        unknown = set(changes) - {"status", "artifact", "error", "report_quality_status"}
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"task fields cannot be updated: {names}")
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM research_tasks WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(f"research task not found: {task_id}")
            current = self._parse_task(row[0])
            updated = current.model_copy(
                update={**changes, "updated_at": self._utc_now()},
            )
            updated = ResearchTask.model_validate(updated.model_dump())
            connection.execute(
                """
                UPDATE research_tasks
                SET payload = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    str(task_id),
                ),
            )
        return deepcopy(updated)

    def update_fenced(
        self,
        task_id: UUID,
        fencing_token: int,
        execution_id: str,
        **changes: object,
    ) -> ResearchTask | None:
        """Update a task only while the caller owns its current execution fence."""

        if fencing_token < 1:
            raise ValueError("fencing_token must be positive")
        unknown = set(changes) - {"status", "artifact", "error", "report_quality_status"}
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"task fields cannot be updated: {names}")
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM research_tasks WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(f"research task not found: {task_id}")
            current = self._parse_task(row[0])
            fence = connection.execute(
                """
                SELECT attempt_count FROM task_requests
                WHERE task_id = ? AND state = 'dispatched'
                  AND fencing_token = ? AND execution_id = ?
                  AND lease_until IS NOT NULL AND lease_until > ?
                """,
                (
                    str(task_id),
                    fencing_token,
                    execution_id,
                    self._utc_now().isoformat(),
                ),
            ).fetchone()
            if fence is None:
                self._record_stale_rejection(
                    connection,
                    task_id,
                    current.status.value,
                    execution_id,
                )
                return None
            updated = current.model_copy(
                update={**changes, "updated_at": self._utc_now()},
            )
            updated = ResearchTask.model_validate(updated.model_dump())
            connection.execute(
                """
                UPDATE research_tasks SET payload = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    str(task_id),
                ),
            )
        return deepcopy(updated)

    def _record_stale_rejection(
        self,
        connection: sqlite3.Connection,
        task_id: UUID,
        status: str,
        execution_id: str,
    ) -> None:
        try:
            attempt_count = int(execution_id.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            return
        existing = connection.execute(
            """
            SELECT 1 FROM task_events
            WHERE task_id = ? AND event_type = 'stale_worker_rejected'
              AND attempt_count = ?
            """,
            (str(task_id), attempt_count),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO task_events(
                    task_id, event_type, host_id, status,
                    attempt_count, duration_ms, created_at
                ) VALUES (?, 'stale_worker_rejected', NULL, ?, ?, NULL, ?)
                """,
                (
                    str(task_id),
                    status,
                    attempt_count,
                    self._utc_now().isoformat(),
                ),
            )

    def delete(self, task_id: UUID) -> bool:
        """Delete one task and report whether a row was removed."""

        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM research_tasks WHERE task_id = ?",
                (str(task_id),),
            )
            return cursor.rowcount > 0

    def list(self) -> list[ResearchTask]:
        """Return isolated tasks ordered by creation time and task ID."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM research_tasks
                ORDER BY created_at ASC, task_id ASC
                """
            ).fetchall()
        return [deepcopy(self._parse_task(row[0])) for row in rows]

    def _initialize(self) -> None:
        try:
            with self._lock, self._connection() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_tasks (
                        task_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
        except sqlite3.Error as error:
            raise PersistentTaskStoreError(
                "persistent task store initialization failed"
            ) from error

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self.database_path,
                timeout=10,
                isolation_level=None,
            )
            connection.execute("PRAGMA busy_timeout = 10000")
            return connection
        except sqlite3.Error as error:
            raise PersistentTaskStoreError(
                "persistent task store connection failed"
            ) from error

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

    @staticmethod
    def _parse_task(payload: str) -> ResearchTask:
        try:
            return ResearchTask.model_validate_json(payload)
        except Exception as error:
            raise PersistentTaskStoreError(
                "stored research task JSON is invalid"
            ) from error

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC)
