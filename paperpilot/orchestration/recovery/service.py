"""Deterministic recovery decisions derived from checkpoint state."""

from copy import deepcopy
from uuid import UUID

from paperpilot.orchestration.checkpoint import (
    CheckpointError,
    CheckpointNotFoundError,
    CheckpointStore,
)
from paperpilot.orchestration.config import OrchestratorConfig
from paperpilot.orchestration.enums import NextAction, ResearchStep
from paperpilot.orchestration.errors import StateValidationError
from paperpilot.orchestration.state import ResearchState, validate_state

from .exceptions import RecoveryError, RecoveryStateInvalidError
from .models import RecoveryAction, RecoveryDecision


class RecoveryService:
    """Validate a stored state and select a deterministic recovery action."""

    def __init__(
        self,
        checkpoint_store: CheckpointStore,
        orchestrator_config: OrchestratorConfig,
    ) -> None:
        self.checkpoint_store = checkpoint_store
        self.orchestrator_config = orchestrator_config

    def recover(self, run_id: UUID) -> RecoveryDecision:
        """Load one checkpoint and return an isolated, validated decision."""

        try:
            record = self.checkpoint_store.load(run_id)
        except CheckpointNotFoundError as error:
            raise RecoveryError(f"checkpoint not found for run_id {run_id}") from error
        except CheckpointError as error:
            message = f"could not load checkpoint for run_id {run_id}"
            raise RecoveryError(message) from error

        if record.run_id != run_id:
            raise RecoveryStateInvalidError(
                "checkpoint run_id does not match the requested run"
            )

        try:
            state = validate_state(deepcopy(record.state))
        except StateValidationError as error:
            raise RecoveryStateInvalidError(
                "checkpoint contains an invalid research state"
            ) from error

        return self._decide(deepcopy(state))

    def _decide(self, state: ResearchState) -> RecoveryDecision:
        step = state["current_step"]

        if step in (ResearchStep.INITIALIZED, ResearchStep.PLANNING):
            return self._decision(
                state,
                RecoveryAction.RESUME,
                "workflow can resume from its saved initialization state",
            )
        if step is ResearchStep.RETRIEVAL:
            if not state["papers"]:
                return self._retry_or_abort(
                    state,
                    ResearchStep.RETRIEVAL,
                    "retrieval produced no papers",
                )
            return self._decision(
                state,
                RecoveryAction.ABORT,
                "retrieval checkpoint is inconsistent with pending recovery",
                failed_stage=ResearchStep.RETRIEVAL,
            )
        if step is ResearchStep.INGESTION:
            if state["documents"]:
                return self._decision(
                    state,
                    RecoveryAction.RESUME,
                    "parsed documents are available for continued processing",
                )
            return self._retry_or_abort(
                state,
                ResearchStep.INGESTION,
                "ingestion produced no documents",
            )
        if step is ResearchStep.READING:
            if state["analyses"]:
                return self._decision(
                    state,
                    RecoveryAction.RESUME,
                    "paper analyses are available for continued processing",
                )
            return self._retry_or_abort(
                state,
                ResearchStep.READING,
                "reading produced no paper analyses",
            )
        if step is ResearchStep.VERIFICATION:
            if state["verified_results"]:
                return self._decision(
                    state,
                    RecoveryAction.RESUME,
                    "verified paper results are available for quality evaluation",
                )
            return self._retry_or_abort(
                state,
                ResearchStep.VERIFICATION,
                "verification produced no verified results",
            )
        if step in (ResearchStep.QUALITY_GATE, ResearchStep.COMPLETED):
            return self._quality_decision(state)
        if step is ResearchStep.FAILED:
            return self._decision(
                state,
                RecoveryAction.ABORT,
                "workflow checkpoint is already marked as failed",
                failed_stage=ResearchStep.FAILED,
            )
        raise RecoveryStateInvalidError(f"unsupported recovery step: {step!r}")

    def _quality_decision(self, state: ResearchState) -> RecoveryDecision:
        actions = {
            NextAction.COMPLETE: RecoveryAction.COMPLETE,
            NextAction.COMPLETE_DEGRADED: RecoveryAction.COMPLETE_DEGRADED,
            NextAction.HUMAN_REVIEW: RecoveryAction.HUMAN_REVIEW,
            NextAction.ABORT: RecoveryAction.ABORT,
        }
        recovery_action = actions.get(state["next_action"])
        if recovery_action is None:
            raise RecoveryStateInvalidError(
                "quality checkpoint contains a nonterminal next_action"
            )
        return self._decision(
            state,
            recovery_action,
            f"quality gate selected {state['next_action'].value}",
            failed_stage=(
                ResearchStep.QUALITY_GATE
                if recovery_action is RecoveryAction.ABORT
                else None
            ),
        )

    def _retry_or_abort(
        self,
        state: ResearchState,
        stage: ResearchStep,
        reason: str,
    ) -> RecoveryDecision:
        remaining = self._remaining_attempts(state, stage)
        if remaining > 0:
            return self._decision(
                state,
                RecoveryAction.RETRY,
                f"{reason}; retry budget remains",
                failed_stage=stage,
                retry_stage=stage.value,
                remaining_attempts=remaining,
            )
        return self._decision(
            state,
            RecoveryAction.ABORT,
            f"{reason}; retry budget is exhausted",
            failed_stage=stage,
        )

    def _remaining_attempts(
        self,
        state: ResearchState,
        stage: ResearchStep,
    ) -> int:
        limit_fields = {
            ResearchStep.RETRIEVAL: "max_retrieval_attempts",
            ResearchStep.INGESTION: "max_ingestion_attempts_per_paper",
            ResearchStep.READING: "max_reader_attempts_per_paper",
            ResearchStep.VERIFICATION: "max_verifier_attempts_per_paper",
        }
        limit_field = limit_fields.get(stage)
        if limit_field is None:
            raise RecoveryStateInvalidError(
                f"stage {stage.value!r} does not support retries"
            )
        attempts = state.get("attempts")
        if attempts is None:
            raise RecoveryStateInvalidError("checkpoint state is missing attempts")
        used = attempts.get(stage.value, 0)
        limit = getattr(self.orchestrator_config, limit_field)
        return max(0, limit - used)

    @staticmethod
    def _decision(
        state: ResearchState,
        action: RecoveryAction,
        reason: str,
        *,
        failed_stage: ResearchStep | None = None,
        retry_stage: str | None = None,
        remaining_attempts: int = 0,
    ) -> RecoveryDecision:
        return RecoveryDecision(
            action=action,
            reason=reason,
            state=deepcopy(state),
            failed_stage=failed_stage,
            retry_stage=retry_stage,
            remaining_attempts=remaining_attempts,
        )
