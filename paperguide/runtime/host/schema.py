"""Versioned SQLite schema migrations for runtime host coordination."""

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from .exceptions import SchemaMigrationError

CURRENT_SCHEMA_VERSION = 6
Migration = Callable[[sqlite3.Connection], None]


def migrate_schema(connection: sqlite3.Connection) -> int:
    """Upgrade a runtime database to the current schema version."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    current = _current_version(connection)
    if current > CURRENT_SCHEMA_VERSION:
        raise SchemaMigrationError(
            "runtime database schema is newer than this application"
        )
    migrations: dict[int, Migration] = {
        1: _migrate_to_version_1,
        2: _migrate_to_version_2,
        3: _migrate_to_version_3,
        4: _migrate_to_version_4,
        5: _migrate_to_version_5,
        6: _migrate_to_version_6,
    }
    while current < CURRENT_SCHEMA_VERSION:
        target = current + 1
        try:
            migrations[target](connection)
            connection.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (target, datetime.now(UTC).isoformat()),
            )
        except sqlite3.Error as error:
            raise SchemaMigrationError(
                f"runtime schema migration {target} failed"
            ) from error
        current = target
    return current


def get_schema_version(connection: sqlite3.Connection) -> int:
    """Return the recorded runtime schema version."""

    return _current_version(connection)


def _current_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
    if row is not None and row[0] is not None:
        return int(row[0])
    return 0


def _migrate_to_version_1(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_requests (
            task_id TEXT PRIMARY KEY,
            request_json TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            lease_owner TEXT,
            lease_until TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_host (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            host_id TEXT NOT NULL,
            heartbeat TEXT NOT NULL,
            pid INTEGER NOT NULL DEFAULT 0,
            version TEXT NOT NULL DEFAULT 'unknown',
            started_at TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'stopped'
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            host_id TEXT,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            duration_ms REAL,
            created_at TEXT NOT NULL
        )
        """
    )
    _ensure_column(connection, "task_requests", "lease_owner", "TEXT")
    _ensure_column(connection, "task_requests", "lease_until", "TEXT")
    _ensure_column(
        connection,
        "task_requests",
        "attempt_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(connection, "runtime_host", "pid", "INTEGER DEFAULT 0")
    _ensure_column(
        connection,
        "runtime_host",
        "version",
        "TEXT NOT NULL DEFAULT 'unknown'",
    )
    _ensure_column(
        connection,
        "runtime_host",
        "started_at",
        "TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(
        connection,
        "runtime_host",
        "status",
        "TEXT NOT NULL DEFAULT 'stopped'",
    )


def _migrate_to_version_2(connection: sqlite3.Connection) -> None:
    _ensure_column(
        connection,
        "task_requests",
        "fencing_token",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(connection, "task_requests", "execution_id", "TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_requests_claim
        ON task_requests(state, lease_until, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_events_task
        ON task_events(task_id, event_id)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_task_execution_id
        ON task_requests(execution_id)
        WHERE execution_id IS NOT NULL
        """
    )


def _migrate_to_version_3(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dead_letter_tasks (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL UNIQUE,
            execution_id TEXT NOT NULL,
            last_status TEXT NOT NULL,
            last_error_type TEXT NOT NULL,
            failed_stage TEXT NOT NULL,
            attempt_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _migrate_to_version_4(connection: sqlite3.Connection) -> None:
    """Add a safe JSON payload and private logical idempotency key."""

    _ensure_column(connection, "task_events", "progress_json", "TEXT")
    _ensure_column(connection, "task_events", "dedupe_key", "TEXT")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_task_events_dedupe
        ON task_events(task_id, dedupe_key)
        WHERE dedupe_key IS NOT NULL
        """
    )


def _migrate_to_version_5(connection: sqlite3.Connection) -> None:
    """Add a private JSON channel for safe internal diagnostics.

    Public event projection continues to read only ``progress_json``.  The
    diagnostic payload is intentionally kept in the existing task_events table
    and is never returned by the public task-events API.
    """

    _ensure_column(connection, "task_events", "diagnostic_json", "TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dead_letter_created
        ON dead_letter_tasks(created_at, task_id)
        """
    )


def _migrate_to_version_6(connection: sqlite3.Connection) -> None:
    """Add private explicit commands executed only by the active TaskHost."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_preflight_requests (
            request_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            result_json TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_provider_preflight_state
        ON provider_preflight_requests(state, created_at)
        """
    )


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    existing = {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in existing:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
        )
