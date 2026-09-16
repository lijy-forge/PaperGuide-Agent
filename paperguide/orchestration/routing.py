"""Pure conditional routing functions for future graph assembly."""

from typing import Any, cast

from paperguide.document import IngestionStatus

from .config import OrchestratorConfig
from .enums import NextAction, PaperStageStatus, ResearchStep
from .state import ResearchState

PLANNER_NODE = "planner"
RETRIEVER_NODE = "retriever"
INGESTION_NODE = "ingestion"
READER_NODE = "reader"
VERIFIER_NODE = "verifier"
QUALITY_GATE_NODE = "quality_gate"
HUMAN_REVIEW_NODE = "human_review"
END_NODE = "end"

VALID_NODE_NAMES = frozenset(
    {
        PLANNER_NODE,
        RETRIEVER_NODE,
        INGESTION_NODE,
        READER_NODE,
        VERIFIER_NODE,
        QUALITY_GATE_NODE,
        HUMAN_REVIEW_NODE,
        END_NODE,
    }
)


class RoutingError(ValueError):
    """Raised when routing state is missing, unknown, or internally invalid."""


def check_retry_budget(
    state: ResearchState,
    stage: str | ResearchStep,
    config: OrchestratorConfig | None = None,
) -> bool:
    """Return whether a stage's nonnegative attempt count is below its limit."""

    stage_name = stage.value if isinstance(stage, ResearchStep) else str(stage)
    limits = {
        ResearchStep.RETRIEVAL.value: "max_retrieval_attempts",
        ResearchStep.INGESTION.value: "max_ingestion_attempts_per_paper",
        ResearchStep.READING.value: "max_reader_attempts_per_paper",
        ResearchStep.VERIFICATION.value: "max_verifier_attempts_per_paper",
    }
    limit_field = limits.get(stage_name)
    if limit_field is None:
        raise RoutingError(f"unknown retry stage: {stage_name!r}")
    if "attempts" not in state:
        raise RoutingError("state is missing attempts")
    attempts = state["attempts"]
    if not isinstance(attempts, dict):
        raise RoutingError("state attempts must be a dictionary")
    attempt = attempts.get(stage_name, 0)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        raise RoutingError(f"invalid attempt count for stage {stage_name!r}")

    resolved_config = config or _state_config(state)
    limit = getattr(resolved_config, limit_field)
    return attempt < limit


def route_after_planner(state: ResearchState) -> str:
    """Route a completed PlannerNode state."""

    action = _next_action(state)
    if action is NextAction.RETRIEVE:
        return RETRIEVER_NODE
    if action is NextAction.ABORT:
        return END_NODE
    return QUALITY_GATE_NODE


def route_after_retrieval(state: ResearchState) -> str:
    """Route retrieval success, bounded retry, or quality evaluation."""

    action = _next_action(state)
    if action is NextAction.INGEST:
        return INGESTION_NODE
    if action is NextAction.RETRY_RETRIEVAL and check_retry_budget(
        state, ResearchStep.RETRIEVAL
    ):
        return RETRIEVER_NODE
    return QUALITY_GATE_NODE


def route_after_ingestion(state: ResearchState) -> str:
    """Route ingestion success or retry only when failed papers remain."""

    action = _next_action(state)
    if action is NextAction.READ:
        return READER_NODE
    if (
        action is NextAction.RETRY_INGESTION
        and _has_failed_papers(state)
        and check_retry_budget(state, ResearchStep.INGESTION)
    ):
        return INGESTION_NODE
    return QUALITY_GATE_NODE


def route_after_reading(state: ResearchState) -> str:
    """Route successful reading, bounded retry, or quality evaluation."""

    action = _next_action(state)
    if action is NextAction.VERIFY:
        return VERIFIER_NODE
    if action is NextAction.RETRY_READING and check_retry_budget(
        state, ResearchStep.READING
    ):
        return READER_NODE
    return QUALITY_GATE_NODE


def route_after_verification(state: ResearchState) -> str:
    """Route verification completion or bounded retry."""

    action = _next_action(state)
    if action is NextAction.EVALUATE_QUALITY:
        return QUALITY_GATE_NODE
    if action is NextAction.RETRY_VERIFICATION and check_retry_budget(
        state, ResearchStep.VERIFICATION
    ):
        return VERIFIER_NODE
    return QUALITY_GATE_NODE


def route_after_quality_gate(state: ResearchState) -> str:
    """Route a quality decision, giving configured conflicts highest priority."""

    config = _state_config(state)
    if _quality_has_conflicts(state) and config.route_conflicts_to_human_review:
        return HUMAN_REVIEW_NODE

    action = _next_action(state)
    routes = {
        NextAction.COMPLETE: END_NODE,
        NextAction.COMPLETE_DEGRADED: END_NODE,
        NextAction.HUMAN_REVIEW: HUMAN_REVIEW_NODE,
        NextAction.RETRY_INGESTION: INGESTION_NODE,
        NextAction.RETRY_READING: READER_NODE,
        NextAction.RETRY_VERIFICATION: VERIFIER_NODE,
        NextAction.RETRY_RETRIEVAL: RETRIEVER_NODE,
        NextAction.ABORT: END_NODE,
    }
    route = routes.get(action)
    if route is None:
        raise RoutingError(f"unsupported quality-gate action: {action.value!r}")
    return route


def _next_action(state: ResearchState) -> NextAction:
    if "next_action" not in state:
        raise RoutingError("state is missing next_action")
    action = state["next_action"]
    if isinstance(action, NextAction):
        return action
    try:
        return NextAction(action)
    except (TypeError, ValueError) as error:
        raise RoutingError(f"unknown next_action: {action!r}") from error


def _state_config(state: ResearchState) -> OrchestratorConfig:
    raw_state = cast(dict[str, Any], state)
    candidate = raw_state.get("orchestrator_config")
    if candidate is None:
        return OrchestratorConfig()
    if isinstance(candidate, OrchestratorConfig):
        return candidate
    try:
        return OrchestratorConfig.model_validate(candidate)
    except Exception as error:
        raise RoutingError("state contains an invalid orchestrator_config") from error


def _has_failed_papers(state: ResearchState) -> bool:
    if any(
        record.status is PaperStageStatus.FAILED
        for record in state.get("paper_status", {}).values()
    ):
        return True
    ingestion_result = state.get("ingestion_result")
    if ingestion_result is not None and any(
        item.status is IngestionStatus.FAILED for item in ingestion_result.items
    ):
        return True
    return any(
        error.stage is ResearchStep.INGESTION and error.paper_id is not None
        for error in state.get("errors", [])
    )


def _quality_has_conflicts(state: ResearchState) -> bool:
    summary = state.get("quality_summary")
    if summary is None:
        return False
    if not isinstance(summary, dict):
        raise RoutingError("quality_summary must be a dictionary")
    conflicts = summary.get("conflicts", 0)
    if isinstance(conflicts, bool) or not isinstance(conflicts, (int, float)):
        raise RoutingError("quality_summary conflicts must be a nonnegative number")
    if conflicts < 0:
        raise RoutingError("quality_summary conflicts cannot be negative")
    return conflicts > 0 or summary.get("has_conflicts") is True
