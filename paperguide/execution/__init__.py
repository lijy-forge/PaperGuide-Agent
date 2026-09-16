"""Public background task execution contracts and in-memory implementation."""

from paperguide.runtime_context import (
    CancellationTokenProtocol,
    ExecutionAbortedError,
    ExecutionCancellationToken,
    ExecutionContext,
    execution_scope,
    get_execution_context,
)
from .exceptions import TaskExecutionError, TaskSubmissionError
from .memory import InMemoryTaskExecutor
from .models import TaskHandle
from .protocol import TaskExecutorProtocol
from .sqlite import PersistentTaskStore, PersistentTaskStoreError

__all__ = [
    "CancellationTokenProtocol",
    "ExecutionAbortedError",
    "ExecutionCancellationToken",
    "ExecutionContext",
    "InMemoryTaskExecutor",
    "PersistentTaskStore",
    "PersistentTaskStoreError",
    "TaskExecutionError",
    "TaskExecutorProtocol",
    "TaskHandle",
    "TaskSubmissionError",
    "execution_scope",
    "get_execution_context",
]
