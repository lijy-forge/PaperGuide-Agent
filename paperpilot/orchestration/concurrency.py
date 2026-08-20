"""Small, shared concurrency primitives for paper-level work."""

from threading import BoundedSemaphore


class LLMCallLimiter:
    """Bound concurrent synchronous LLM calls across orchestration nodes."""

    def __init__(self, maximum: int) -> None:
        self._semaphore = BoundedSemaphore(maximum)

    def __enter__(self) -> "LLMCallLimiter":
        self._semaphore.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._semaphore.release()
