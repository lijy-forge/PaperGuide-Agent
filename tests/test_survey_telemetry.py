"""Private-only, scalar telemetry tests for survey synthesis failures."""

import unittest
from uuid import uuid4

from paperguide.analysis.exceptions import (
    AnalysisLLMResponseError,
    AnalysisSchemaValidationError,
)
from paperguide.application import ResearchTaskStatus
from paperguide.progress.events import TaskEventType
from paperguide.reporting.exceptions import ReportSchemaValidationError
from paperguide.reporting.survey_telemetry import SurveyTelemetry
from paperguide.runtime.host import SQLiteHostBroker


class _StatusError(RuntimeError):
    def __init__(self, status_code: int, secret: str = "secret-prompt") -> None:
        super().__init__(secret)
        self.status_code = status_code


class SurveyTelemetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[tuple[TaskEventType, dict[str, object], float | None]] = []
        self.telemetry = SurveyTelemetry(
            lambda event_type, payload, duration: self.events.append(
                (event_type, payload, duration)
            )
        )
        self.telemetry.update_input_counts(
            input_paper_count=5,
            input_statement_count=12,
            citation_capable_statement_count=8,
            core_paper_count=5,
            registered_citation_count=5,
            taxonomy_family_count=3,
            comparison_row_count=5,
        )

    def last(self) -> dict[str, object]:
        return self.events[-1][1]

    def test_stage_and_substage_lifecycle_is_scalar_only(self) -> None:
        self.telemetry.stage_started()
        started = self.telemetry.substage_started("taxonomy")
        self.telemetry.substage_completed("taxonomy", started)
        self.telemetry.stage_completed()
        self.assertEqual(self.events[0][0], TaskEventType.SURVEY_STAGE_STARTED)
        self.assertEqual(self.events[-1][0], TaskEventType.SURVEY_STAGE_COMPLETED)
        self.assertEqual(self.last()["input_paper_count"], 5)

    def test_provider_failures_are_safely_classified(self) -> None:
        cases = {
            401: "PROVIDER_AUTH",
            402: "PROVIDER_BILLING",
            429: "PROVIDER_RATE_LIMIT",
            503: "PROVIDER_SERVER_ERROR",
        }
        for status, category in cases.items():
            with self.subTest(status=status):
                started = self.telemetry.llm_started("synthesis_a", 1, 100)
                self.telemetry.llm_failed("synthesis_a", 1, started, _StatusError(status))
                self.assertEqual(self.last()["failure_category"], category)
                self.assertNotIn("secret-prompt", str(self.last()))

    def test_timeout_connection_context_and_structured_failures_are_distinct(self) -> None:
        cases = (
            (TimeoutError("hidden"), "PROVIDER_TIMEOUT"),
            (ConnectionError("hidden"), "PROVIDER_CONNECTION"),
            (RuntimeError("maximum context length hidden"), "CONTEXT_LENGTH"),
            (AnalysisLLMResponseError("hidden"), "STRUCTURED_OUTPUT_PARSE"),
            (AnalysisSchemaValidationError("hidden"), "SCHEMA_VALIDATION"),
        )
        for error, category in cases:
            with self.subTest(error=type(error).__name__):
                started = self.telemetry.llm_started("synthesis_b", 2, 321)
                self.telemetry.llm_failed("synthesis_b", 2, started, error)
                self.assertEqual(self.last()["failure_category"], category)
                self.assertEqual(self.last()["estimated_input_char_count"], 321)
                self.assertNotIn("hidden", str(self.last()))

    def test_success_records_structured_output_boundaries(self) -> None:
        started = self.telemetry.llm_started("synthesis_c", 3, 456)
        self.telemetry.llm_succeeded("synthesis_c", 3, started)
        payload = self.last()
        self.assertTrue(payload["provider_response_reached"])
        self.assertTrue(payload["json_parse_reached"])
        self.assertTrue(payload["schema_validation_reached"])
        self.assertTrue(payload["application_mapping_reached"])

    def test_report_validation_failure_records_safe_rule_and_field(self) -> None:
        error = ReportSchemaValidationError("UNKNOWN_PUBLIC_CITATION")
        error.validation_rule = "UNKNOWN_PUBLIC_CITATION"
        error.validation_field = "report.sections[].paragraphs[].citation_refs[]"
        started = self.telemetry.substage_started("citation_safe_validation")
        self.telemetry.substage_failed("citation_safe_validation", started, error)
        payload = self.last()
        self.assertEqual(payload["validation_rule"], "UNKNOWN_PUBLIC_CITATION")
        self.assertEqual(payload["validation_field"], "report.sections[].paragraphs[].citation_refs[]")
        self.assertEqual(payload["violation_count"], 1)

    def test_telemetry_publisher_failure_does_not_raise(self) -> None:
        telemetry = SurveyTelemetry(lambda *_args: (_ for _ in ()).throw(RuntimeError("ignored")))
        telemetry.stage_started()
        telemetry.stage_completed()

    def test_private_events_are_excluded_from_public_broker_projection(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            broker = SQLiteHostBroker(Path(directory) / "runtime.sqlite3")
            task_id = uuid4()
            broker.record_diagnostic_event(
                task_id,
                TaskEventType.SURVEY_LLM_CALL_FAILED,
                ResearchTaskStatus.RUNNING,
                {
                    "substage": "synthesis_a",
                    "failure_category": "PROVIDER_TIMEOUT",
                    "safe_exception_class": "ProviderTimeoutError",
                    "input_paper_count": 5,
                },
            )
            self.assertEqual(broker.list_events(task_id), [])
            private = broker.list_diagnostic_events(task_id)
        self.assertEqual(len(private), 1)
        self.assertNotIn("secret", str(private))


if __name__ == "__main__":
    unittest.main()
