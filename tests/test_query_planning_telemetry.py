"""Safe Q0 telemetry and retrieval-planning contract tests."""

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from paperpilot.analysis import (
    AnalysisLLMInvocationError,
    AnalysisLLMResponseError,
    AnalysisSchemaValidationError,
)
from paperpilot.domain import PaperSource, ResearchConfig
from paperpilot.orchestration import create_initial_state
from paperpilot.orchestration.nodes import PlannerNode
from paperpilot.progress.events import TaskEventType
from paperpilot.progress.publisher import ProgressPublisher
from paperpilot.relevance import (
    QueryVariant,
    ResearchIntent,
    RetrievalPlanService,
)
from paperpilot.runtime.host import SQLiteHostBroker


class _Planner:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def plan(self, question):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class _Expander:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def expand(self, intent):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.result)


def _intent() -> ResearchIntent:
    return ResearchIntent(
        research_question="目标检测与视觉 SLAM 融合",
        required_concepts=["object detection", "visual SLAM"],
        related_concepts=["semantic mapping"],
        relation_requirements=["fusion"],
        exclusion_concepts=["LiDAR only"],
        domain="robotics",
        query_language="en",
    )


def _variants(count: int = 5) -> list[QueryVariant]:
    return [
        QueryVariant(query=f"object detection visual SLAM fusion {index}", purpose="direct")
        for index in range(count)
    ]


class QueryPlanningTelemetryTests(unittest.TestCase):
    def test_success_records_planner_and_expansion_counts(self) -> None:
        events = []
        plan = RetrievalPlanService(_Planner(_intent()), _Expander(_variants())).build(
            "目标检测与视觉 SLAM 融合",
            max_core_papers=5,
            diagnostic_callback=events.append,
        )

        self.assertEqual(plan.planned_query_count, 5)
        self.assertEqual(
            [(event.stage, event.outcome) for event in events],
            [
                ("intent_planner", "started"),
                ("intent_planner", "succeeded"),
                ("query_expansion", "started"),
                ("query_expansion", "succeeded"),
            ],
        )
        self.assertEqual(events[1].required_concept_count, 2)
        self.assertEqual(events[3].output_count, 5)

    def test_provider_timeout_is_classified_without_message(self) -> None:
        try:
            raise TimeoutError("secret endpoint and token")
        except TimeoutError as cause:
            error = AnalysisLLMInvocationError("safe wrapper")
            error.__cause__ = cause
        events = []
        service = RetrievalPlanService(_Planner(error=error), _Expander(_variants()))

        service.build("question", max_core_papers=5, diagnostic_callback=events.append)

        fallback = next(event for event in events if event.outcome == "fallback")
        self.assertEqual(fallback.failure_category, "PROVIDER_TIMEOUT")
        self.assertEqual(fallback.exception_class_safe, "TimeoutError")
        self.assertNotIn("secret", fallback.model_dump_json())

    def test_parse_failure_records_json_boundary(self) -> None:
        events = []
        service = RetrievalPlanService(
            _Planner(_intent()),
            _Expander(error=AnalysisLLMResponseError("raw response omitted")),
        )

        service.build("question", max_core_papers=5, diagnostic_callback=events.append)

        fallback = events[-1]
        self.assertEqual(fallback.failure_category, "STRUCTURED_OUTPUT_PARSE")
        self.assertTrue(fallback.json_parse_reached)
        self.assertFalse(fallback.schema_validation_reached)

    def test_schema_failure_is_distinct(self) -> None:
        events = []
        service = RetrievalPlanService(
            _Planner(error=AnalysisSchemaValidationError("schema omitted")),
            _Expander(_variants()),
        )

        service.build("question", max_core_papers=5, diagnostic_callback=events.append)

        fallback = next(event for event in events if event.outcome == "fallback")
        self.assertEqual(fallback.failure_category, "SCHEMA_VALIDATION")
        self.assertTrue(fallback.schema_validation_reached)

    def test_empty_expansion_is_invalid_output_fallback(self) -> None:
        events = []
        plan = RetrievalPlanService(_Planner(_intent()), _Expander([])).build(
            "original question",
            max_core_papers=5,
            diagnostic_callback=events.append,
        )

        self.assertEqual(plan.planned_query_count, 1)
        self.assertEqual(events[-1].failure_category, "INVALID_EXPANSION_OUTPUT")
        self.assertEqual(events[-1].fallback_query_count, 1)

    def test_one_valid_variant_is_legal_and_not_fallback(self) -> None:
        events = []
        plan = RetrievalPlanService(
            _Planner(_intent()), _Expander(_variants(1))
        ).build("question", max_core_papers=5, diagnostic_callback=events.append)

        self.assertEqual(plan.planned_query_count, 1)
        self.assertNotIn("QUERY_EXPANSION_FALLBACK", plan.warnings)
        self.assertEqual(events[-1].outcome, "succeeded")

    def test_queries_remain_unique_and_bounded(self) -> None:
        variants = [*_variants(5), _variants(1)[0]]
        plan = RetrievalPlanService(_Planner(_intent()), _Expander(variants)).build(
            "question", max_core_papers=5
        )

        self.assertEqual(plan.planned_query_count, 5)
        self.assertEqual(len({item.query.casefold() for item in plan.query_variants}), 5)

    def test_fallback_does_not_add_llm_calls(self) -> None:
        planner = _Planner(error=RuntimeError("planner failed"))
        expander = _Expander(error=RuntimeError("expander failed"))

        RetrievalPlanService(planner, expander).build("question", max_core_papers=5)

        self.assertEqual(planner.calls, 1)
        self.assertEqual(expander.calls, 1)

    def test_private_planning_diagnostics_are_not_public_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker = SQLiteHostBroker(Path(directory) / "runtime.sqlite3")
            publisher = ProgressPublisher(broker)
            task_id, run_id = uuid4(), uuid4()
            publisher.bind(run_id, task_id)
            config = ResearchConfig(
                question="目标检测与视觉 SLAM 融合",
                max_papers=5,
                sources=[PaperSource.ARXIV],
            )
            state = create_initial_state(config.question, config)
            state["run_id"] = run_id

            PlannerNode(
                RetrievalPlanService(_Planner(_intent()), _Expander(_variants())),
                publisher,
            ).execute(state)

            public = broker.list_events(task_id)
            private = broker.list_diagnostic_events(task_id)
        self.assertFalse(
            any(event.event_type.value.startswith("intent_planner") for event in public)
        )
        self.assertIn("intent_planner_succeeded", {event["event_type"] for event in private})
        self.assertNotIn("目标检测", str(private))


if __name__ == "__main__":
    unittest.main()
