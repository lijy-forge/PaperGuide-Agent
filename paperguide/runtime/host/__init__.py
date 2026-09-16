"""Persistent local task host, SQLite broker, and CLI client."""

from .broker import SQLiteHostBroker
from .client import PersistentTaskHostClient
from .exceptions import (
    SchemaMigrationError,
    TaskHostAlreadyRunningError,
    TaskHostError,
    TaskHostUnavailableError,
)
from .hardening import (
    DeadLetterService,
    DeadLetterServiceProtocol,
    RuntimeReconciler,
    RuntimeReconcilerProtocol,
    RuntimeRecoveryProtocol,
    RuntimeRecoveryService,
)
from .lease import LeaseMonitorProtocol, WorkerLeaseMonitor
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
from .preflight import (
    HostProviderPreflight,
    ProviderFailureCategory,
    ProviderPreflightResult,
    ProviderPreflightStatus,
)
from .schema import CURRENT_SCHEMA_VERSION
from .service import TaskHost, create_task_host_client

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DeadLetterTask",
    "DeadLetterService",
    "DeadLetterServiceProtocol",
    "HostStatus",
    "HostProviderPreflight",
    "LeaseLossReason",
    "LeaseMonitorProtocol",
    "LeaseRenewalResult",
    "PersistentTaskHostClient",
    "ProviderFailureCategory",
    "ProviderPreflightResult",
    "ProviderPreflightStatus",
    "RuntimeHostMetadata",
    "RuntimeMetrics",
    "RuntimeRecoveryResult",
    "RuntimeReconciler",
    "RuntimeReconcilerProtocol",
    "RuntimeRecoveryProtocol",
    "RuntimeRecoveryService",
    "SchemaMigrationError",
    "SQLiteHostBroker",
    "TaskHost",
    "TaskHostAlreadyRunningError",
    "TaskHostError",
    "TaskHostUnavailableError",
    "TaskEvent",
    "TaskEventType",
    "TaskLease",
    "WorkerLeaseMonitor",
    "create_task_host_client",
]
