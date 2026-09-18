"""Run the research graph under a checkpointer so a failed run can continue.

A research task takes minutes and spends most of them on LLM calls and PDF
downloads. Without persistence, a worker dying at the twelfth paper discards
the eleven already read and pays for them again. LangGraph records the state
after each node, which makes the work already done recoverable.

The graph protocol stays ``invoke(state)``. LangGraph needs a thread id to
locate a checkpoint, and the run already carries one, so it is read from the
state rather than added to the signature — every existing caller and test
double keeps working.

Resuming is invoking with ``None`` instead of a state: passing a state starts
the thread over. So a run resumes only when a checkpoint exists and stopped
partway; anything else is a fresh run.

This is the graph's own record of which node runs next, and is separate from
``orchestration.checkpoint``, which stores a state snapshot for the recovery
service to turn into a business decision — resume, retry, degrade, escalate.
One knows where execution stopped, the other what should happen about it.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from paperguide.orchestration.state import ResearchState

LOGGER = logging.getLogger("paperguide.orchestration.resumable")


class CompiledGraphProtocol(Protocol):
    """The part of a compiled LangGraph this wrapper relies on."""

    def invoke(self, state: Any, config: dict[str, Any] | None = None) -> Any: ...

    def get_state(self, config: dict[str, Any]) -> Any: ...


class ResumableGraph:
    """Wrap a checkpointed graph and continue an interrupted run."""

    def __init__(self, compiled: CompiledGraphProtocol) -> None:
        self._compiled = compiled

    def invoke(self, state: ResearchState) -> ResearchState:
        thread_id = self._thread_id(state)
        if thread_id is None:
            # Nothing identifies this run, so it cannot be resumed later
            # either. Running unpersisted is better than inventing an id that
            # would collide with another run's checkpoint.
            return self._compiled.invoke(state)

        config = {"configurable": {"thread_id": thread_id}}
        if self._has_pending_work(config):
            LOGGER.info("resuming research graph from checkpoint")
            return self._compiled.invoke(None, config)
        return self._compiled.invoke(state, config)

    @staticmethod
    def _thread_id(state: ResearchState) -> str | None:
        for key in ("run_id", "task_id"):
            value = state.get(key)
            if value:
                return str(value)
        return None

    def _has_pending_work(self, config: dict[str, Any]) -> bool:
        """Whether a checkpoint exists that stopped before finishing.

        A completed thread reports no next node, and re-invoking it with
        ``None`` would return its final state without doing anything — which
        would silently hand back a stale result for a new request.
        """

        try:
            snapshot = self._compiled.get_state(config)
        except Exception as error:  # noqa: BLE001 - a missing checkpoint is normal
            LOGGER.debug("no usable checkpoint: %s", type(error).__name__)
            return False
        return bool(getattr(snapshot, "next", ()))
