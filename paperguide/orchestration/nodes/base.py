"""Common callable behavior for dependency-injected orchestration nodes."""

from abc import ABC, abstractmethod
from uuid import UUID

from paperguide.orchestration.enums import NextAction, ResearchStep
from paperguide.orchestration.errors import ResearchError
from paperguide.orchestration.state import ResearchState


class BaseNode(ABC):
    """Execute a state transformation with uniform safe error conversion."""

    name = "base"
    error_step = ResearchStep.FAILED
    failure_step: ResearchStep | None = None
    error_next_action = NextAction.ABORT
    error_recoverable = False

    def execute(self, state: ResearchState) -> ResearchState:
        """Return a new state and convert ordinary uncaught exceptions to errors."""

        working_state = self.copy_state(state)
        try:
            return self._execute(working_state)
        except Exception as error:
            failed = self.add_error(
                working_state,
                error=error,
                stage=self.error_step,
                recoverable=self.error_recoverable,
            )
            failed["current_step"] = self.failure_step or self.error_step
            failed["next_action"] = self.error_next_action
            return failed

    def __call__(self, state: ResearchState) -> ResearchState:
        """Allow a node adapter to be used as a plain callable."""

        return self.execute(state)

    @abstractmethod
    def _execute(self, state: ResearchState) -> ResearchState:
        """Implement one node-specific state transformation."""

    def add_error(
        self,
        state: ResearchState,
        *,
        error: Exception | None = None,
        stage: ResearchStep | None = None,
        paper_id: UUID | None = None,
        recoverable: bool | None = None,
        error_type: str | None = None,
        message: str | None = None,
        attempt: int | None = None,
    ) -> ResearchState:
        """Return a copied state with one sanitized ResearchError appended."""

        updated = self.copy_state(state)
        resolved_attempt = (
            attempt
            if attempt is not None
            else updated.get("attempts", {}).get(self.name, 0)
        )
        item = ResearchError(
            stage=stage or self.error_step,
            paper_id=paper_id,
            error_type=error_type or (type(error).__name__ if error else "NodeError"),
            message=message if message is not None else str(error or "Node failed"),
            recoverable=(
                self.error_recoverable if recoverable is None else recoverable
            ),
            attempt=resolved_attempt,
        )
        updated["errors"].append(item)
        return updated

    @staticmethod
    def copy_state(state: ResearchState) -> ResearchState:
        """Copy the state and every mutable top-level collection used by nodes."""

        copied = dict(state)
        for field in ("papers", "errors", "warnings"):
            copied[field] = list(state.get(field, []))
        for field in (
            "documents",
            "analyses",
            "verification_results",
            "verified_results",
            "paper_status",
            "attempts",
            "quality_summary",
            "evidence_linked_analysis",
        ):
            copied[field] = dict(state.get(field, {}))
        return copied  # type: ignore[return-value]
