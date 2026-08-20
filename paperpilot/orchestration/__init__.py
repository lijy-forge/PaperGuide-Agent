"""Public state contract for future PaperPilot research orchestration."""

from .config import OrchestratorConfig
from .enums import NextAction, PaperStageStatus, ResearchStep
from .errors import (
    PaperStageRecord,
    ResearchError,
    StateValidationError,
    sanitize_message,
)
from .graph import build_research_graph, compile_research_graph, human_review_node
from .graph_factory import create_research_graph
from .state import (
    ResearchState,
    create_initial_state,
    state_from_json,
    state_to_json,
    validate_state,
)
from .routing import (
    RoutingError,
    check_retry_budget,
    route_after_ingestion,
    route_after_planner,
    route_after_quality_gate,
    route_after_reading,
    route_after_retrieval,
    route_after_verification,
)

__all__ = [
    "NextAction",
    "OrchestratorConfig",
    "PaperStageRecord",
    "PaperStageStatus",
    "ResearchError",
    "ResearchState",
    "ResearchStep",
    "RoutingError",
    "StateValidationError",
    "build_research_graph",
    "compile_research_graph",
    "create_initial_state",
    "create_research_graph",
    "check_retry_budget",
    "human_review_node",
    "route_after_ingestion",
    "route_after_planner",
    "route_after_quality_gate",
    "route_after_reading",
    "route_after_retrieval",
    "route_after_verification",
    "sanitize_message",
    "state_from_json",
    "state_to_json",
    "validate_state",
]
