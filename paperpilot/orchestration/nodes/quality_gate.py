"""Pure deterministic quality decision node."""

from paperpilot.orchestration.config import OrchestratorConfig
from paperpilot.orchestration.enums import NextAction, ResearchStep
from paperpilot.orchestration.state import ResearchState

from .base import BaseNode


class QualityGateNode(BaseNode):
    """Select a terminal action from verified counts, scores, and conflicts."""

    name = "quality_gate"
    error_step = ResearchStep.QUALITY_GATE
    failure_step = ResearchStep.FAILED
    error_next_action = NextAction.ABORT
    error_recoverable = False

    def __init__(self, config: OrchestratorConfig):
        self.config = config

    def _execute(self, state: ResearchState) -> ResearchState:
        verified_results = state.get("verified_results", {})
        verification_results = state.get("verification_results", {})
        scores = [
            result.verification.verification_score
            for result in verified_results.values()
        ]
        average_score = sum(scores) / len(scores) if scores else 0.0
        has_conflicts = any(
            result.conflicts or result.conflicted_evidence_ids
            for result in verification_results.values()
        )

        if has_conflicts and self.config.route_conflicts_to_human_review:
            next_action = NextAction.HUMAN_REVIEW
            reason = "evidence conflicts require human review"
        elif (
            len(verified_results) >= self.config.minimum_verified_papers
            and average_score >= self.config.minimum_verification_score
        ):
            next_action = NextAction.COMPLETE
            reason = "verification quality thresholds were met"
        elif self.config.allow_degraded_completion and verified_results:
            next_action = NextAction.COMPLETE_DEGRADED
            reason = "partial verified results are available"
        else:
            next_action = NextAction.ABORT
            reason = "verification quality thresholds were not met"

        state["quality_summary"] = {
            "verified_papers": len(verified_results),
            "average_verification_score": average_score,
            "error_count": len(state.get("errors", [])),
            "has_conflicts": has_conflicts,
        }
        state["terminal_reason"] = reason
        state["current_step"] = ResearchStep.QUALITY_GATE
        state["next_action"] = next_action
        return state
