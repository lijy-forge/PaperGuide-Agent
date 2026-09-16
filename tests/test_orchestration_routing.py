"""Unit tests for pure orchestration routing decisions."""

import copy
import unittest
from uuid import uuid4

from paperguide.domain import PaperSource, ResearchConfig
from paperguide.orchestration import (
    NextAction,
    OrchestratorConfig,
    PaperStageRecord,
    PaperStageStatus,
    ResearchStep,
    RoutingError,
    check_retry_budget,
    create_initial_state,
    route_after_ingestion,
    route_after_planner,
    route_after_quality_gate,
    route_after_reading,
    route_after_retrieval,
    route_after_verification,
)


def make_state():
    """Create a valid minimal state for routing tests."""

    config = ResearchConfig(
        question="Analyze SLAM",
        max_papers=5,
        sources=[PaperSource.ARXIV],
    )
    return create_initial_state(config.question, config)


class OrchestrationRoutingTests(unittest.TestCase):
    """Verify fixed routes, bounded retries, validation, and purity."""

    def test_planner_routes_to_retriever(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.RETRIEVE

        self.assertEqual(route_after_planner(state), "retriever")

    def test_planner_abort_routes_to_end(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.ABORT

        self.assertEqual(route_after_planner(state), "end")

    def test_retrieval_retry_with_budget_routes_to_retriever(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.RETRY_RETRIEVAL
        state["attempts"] = {ResearchStep.RETRIEVAL.value: 1}

        self.assertEqual(route_after_retrieval(state), "retriever")

    def test_retrieval_retry_exhaustion_routes_to_quality_gate(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.RETRY_RETRIEVAL
        state["attempts"] = {ResearchStep.RETRIEVAL.value: 2}

        self.assertEqual(route_after_retrieval(state), "quality_gate")

    def test_ingestion_success_routes_to_reader(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.READ

        self.assertEqual(route_after_ingestion(state), "reader")

    def test_ingestion_retry_requires_failed_paper_and_budget(self) -> None:
        state = make_state()
        paper_id = uuid4()
        state["next_action"] = NextAction.RETRY_INGESTION
        state["attempts"] = {ResearchStep.INGESTION.value: 1}
        state["paper_status"] = {
            str(paper_id): PaperStageRecord(
                paper_id=paper_id,
                status=PaperStageStatus.FAILED,
            )
        }

        self.assertEqual(route_after_ingestion(state), "ingestion")

    def test_ingestion_retry_without_failed_paper_routes_to_quality_gate(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.RETRY_INGESTION

        self.assertEqual(route_after_ingestion(state), "quality_gate")

    def test_reading_success_routes_to_verifier(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.VERIFY

        self.assertEqual(route_after_reading(state), "verifier")

    def test_reading_retry_obeys_budget(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.RETRY_READING
        state["attempts"] = {ResearchStep.READING.value: 1}

        self.assertEqual(route_after_reading(state), "reader")
        state["attempts"] = {ResearchStep.READING.value: 2}
        self.assertEqual(route_after_reading(state), "quality_gate")

    def test_verification_routes_to_quality_gate(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.EVALUATE_QUALITY

        self.assertEqual(route_after_verification(state), "quality_gate")

    def test_quality_complete_routes_to_end(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.COMPLETE

        self.assertEqual(route_after_quality_gate(state), "end")

    def test_quality_degraded_routes_to_end(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.COMPLETE_DEGRADED

        self.assertEqual(route_after_quality_gate(state), "end")

    def test_quality_conflict_has_human_review_priority(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.COMPLETE
        state["quality_summary"] = {"conflicts": 1}

        self.assertEqual(route_after_quality_gate(state), "human_review")

    def test_quality_retry_verification_routes_to_verifier(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.RETRY_VERIFICATION

        self.assertEqual(route_after_quality_gate(state), "verifier")

    def test_verification_retry_obeys_budget(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.RETRY_VERIFICATION
        state["attempts"] = {ResearchStep.VERIFICATION.value: 1}

        self.assertEqual(route_after_verification(state), "verifier")
        state["attempts"] = {ResearchStep.VERIFICATION.value: 2}
        self.assertEqual(route_after_verification(state), "quality_gate")

    def test_unknown_action_raises_routing_error(self) -> None:
        state = make_state()
        state["next_action"] = "not-an-action"  # type: ignore[typeddict-item]

        with self.assertRaises(RoutingError):
            route_after_quality_gate(state)

    def test_missing_next_action_raises_routing_error(self) -> None:
        state = make_state()
        del state["next_action"]

        with self.assertRaises(RoutingError):
            route_after_planner(state)

    def test_retry_budget_rejects_invalid_attempts(self) -> None:
        state = make_state()
        state["attempts"] = {ResearchStep.RETRIEVAL.value: -1}

        with self.assertRaises(RoutingError):
            check_retry_budget(state, ResearchStep.RETRIEVAL)

    def test_retry_budget_accepts_explicit_config(self) -> None:
        state = make_state()
        state["attempts"] = {ResearchStep.RETRIEVAL.value: 1}
        config = OrchestratorConfig(max_retrieval_attempts=1)

        self.assertFalse(
            check_retry_budget(state, ResearchStep.RETRIEVAL, config=config)
        )

    def test_routing_does_not_modify_state(self) -> None:
        state = make_state()
        state["next_action"] = NextAction.RETRY_RETRIEVAL
        state["attempts"] = {ResearchStep.RETRIEVAL.value: 1}
        original = copy.deepcopy(state)

        route_after_retrieval(state)

        self.assertEqual(state, original)


if __name__ == "__main__":
    unittest.main()
