"""Zero-dependency cooperative context shared by execution and export layers."""

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import Event
from typing import Iterator, Protocol
from uuid import UUID


class ExecutionAbortedError(RuntimeError):
    """Raised when a worker must stop publishing results after lease loss."""


class CancellationTokenProtocol(Protocol):
    """Cooperative cancellation boundary for long-running worker operations."""

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""

        ...

    def raise_if_cancelled(self) -> None:
        """Raise ExecutionAbortedError when cancellation was requested."""

        ...


class ExecutionCancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise ExecutionAbortedError("execution lease is no longer valid")


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Identity and cancellation state for one fenced task attempt."""

    task_id: UUID
    execution_id: str
    cancellation_token: CancellationTokenProtocol


_CURRENT_EXECUTION: ContextVar[ExecutionContext | None] = ContextVar(
    "paperguide_execution_context",
    default=None,
)


def get_execution_context() -> ExecutionContext | None:
    """Return the current worker execution context, if any."""

    return _CURRENT_EXECUTION.get()


@contextmanager
def execution_scope(context: ExecutionContext | None) -> Iterator[None]:
    """Install an execution context for one synchronous worker call."""

    token: Token[ExecutionContext | None] = _CURRENT_EXECUTION.set(context)
    try:
        yield
    finally:
        _CURRENT_EXECUTION.reset(token)
