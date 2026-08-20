"""Deterministic initialization node for a research workflow."""

import inspect

from paperpilot.orchestration.enums import NextAction, ResearchStep
from paperpilot.orchestration.state import ResearchState
from paperpilot.relevance import PlanningStageDiagnostic, RetrievalPlanService
from paperpilot.progress.models import ProgressEventPayload, ProgressStage
from paperpilot.progress.publisher import ProgressPublisherProtocol
from paperpilot.progress.events import TaskEventType

from .base import BaseNode


class PlannerNode(BaseNode):
    """Validate the minimal starting inputs without invoking an LLM."""

    name = "planner"
    error_step = ResearchStep.PLANNING
    failure_step = ResearchStep.FAILED
    error_next_action = NextAction.ABORT
    error_recoverable = False

    def __init__(self, plan_service: RetrievalPlanService | None = None, progress_publisher: ProgressPublisherProtocol | None = None):
        self.plan_service = plan_service
        self.progress_publisher = progress_publisher

    def _execute(self, state: ResearchState) -> ResearchState:
        self._publish(state, TaskEventType.QUERY_PLANNING_STARTED, ProgressEventPayload(stage=ProgressStage.QUERY_PLANNING))
        if not str(state.get("question", "")).strip():
            raise ValueError("research question must not be empty")
        if state.get("research_config") is None:
            raise ValueError("research_config is required")
        if self.plan_service is not None:
            build = self.plan_service.build
            kwargs = {"max_core_papers": state["research_config"].max_papers}
            if "diagnostic_callback" in inspect.signature(build).parameters:
                kwargs["diagnostic_callback"] = (
                    lambda item: self._publish_planning_diagnostic(state, item)
                )
            plan = build(state["question"], **kwargs)
            state["retrieval_plan"] = plan
            state["warnings"] = list(dict.fromkeys([*state.get("warnings", []), *plan.warnings]))
        state["current_step"] = ResearchStep.PLANNING
        state["next_action"] = NextAction.RETRIEVE
        plan = state.get("retrieval_plan")
        self._publish(state, TaskEventType.QUERY_PLANNING_COMPLETED, ProgressEventPayload(stage=ProgressStage.QUERY_PLANNING, total=(plan.planned_query_count if plan else 0), completed=(plan.planned_query_count if plan else 0)))
        return state

    def _publish(self, state: ResearchState, event_type: TaskEventType, payload: ProgressEventPayload) -> None:
        if self.progress_publisher is not None:
            self.progress_publisher.publish(state["run_id"], event_type, payload)

    def _publish_planning_diagnostic(
        self, state: ResearchState, diagnostic: PlanningStageDiagnostic
    ) -> None:
        publisher = self.progress_publisher
        publish = getattr(publisher, "publish_diagnostic", None)
        if publish is None:
            return
        event_type = {
            ("intent_planner", "started"): TaskEventType.INTENT_PLANNER_STARTED,
            ("intent_planner", "succeeded"): TaskEventType.INTENT_PLANNER_SUCCEEDED,
            ("intent_planner", "fallback"): TaskEventType.INTENT_PLANNER_FALLBACK,
            ("query_expansion", "started"): TaskEventType.QUERY_EXPANSION_STARTED,
            ("query_expansion", "succeeded"): TaskEventType.QUERY_EXPANSION_SUCCEEDED,
            ("query_expansion", "fallback"): TaskEventType.QUERY_EXPANSION_FALLBACK,
        }[(diagnostic.stage, diagnostic.outcome)]
        try:
            publish(
                state["run_id"],
                event_type,
                diagnostic.model_dump(),
                duration_ms=diagnostic.elapsed_ms,
                dedupe_key=f"q0:{diagnostic.stage}:{diagnostic.outcome}",
            )
        except Exception:
            return
