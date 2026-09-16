"""R0.5 safe Reader telemetry and behavior-preservation tests."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from uuid import uuid4

from paperguide.analysis import (
    AnalysisLLMResponseError,
)
from paperguide.document import Document
from paperguide.orchestration import ResearchStep, create_initial_state
from paperguide.orchestration.nodes import ReaderNode
from paperguide.progress.diagnostics import (
    sanitize_reader_exception,
    summarize_reader_diagnostics,
)
from paperguide.progress.events import TaskEventType
from paperguide.runtime.host import SQLiteHostBroker
from pydantic import BaseModel, ValidationError

from .verification_fixtures import make_document


class CapturingPublisher:
    def __init__(self):
        self.public = []
        self.private = []

    def publish(self, run_id, event_type, payload):
        self.public.append((event_type, payload))

    def publish_diagnostic(self, run_id, event_type, payload, **kwargs):
        self.private.append((event_type, dict(payload), kwargs))


class FakeReader:
    def __init__(self, failures=None):
        self.failures = set(failures or [])

    def analyze(self, document: Document):
        if document.paper_id in self.failures:
            raise AnalysisLLMResponseError("raw response must never be persisted")
        return object()


def make_state(documents):
    config = __import__("paperguide.domain", fromlist=["ResearchConfig"]).ResearchConfig(
        question="Analyze SLAM",
        max_papers=5,
        sources=[],
    )
    state = create_initial_state(config.question, config)
    state["documents"] = {str(document.paper_id): document for document in documents}
    return state


class ReaderTelemetryTests(unittest.TestCase):
    def test_bounded_concurrency_and_stable_merge(self):
        class ConcurrentReader:
            def __init__(self):
                self.active = 0
                self.maximum_active = 0
                self.lock = threading.Lock()

            def analyze(self, document):
                with self.lock:
                    self.active += 1
                    self.maximum_active = max(self.maximum_active, self.active)
                time.sleep(0.02)
                with self.lock:
                    self.active -= 1
                return document.title

        documents = [make_document() for _ in range(5)]
        reader = ConcurrentReader()
        result = ReaderNode(reader, max_concurrency=3).execute(make_state(documents))

        self.assertLessEqual(reader.maximum_active, 3)
        self.assertGreaterEqual(reader.maximum_active, 2)
        self.assertEqual(
            list(result["analyses"]), [str(document.paper_id) for document in documents]
        )

    def test_item_started_succeeded_and_stage_completed(self):
        publisher = CapturingPublisher()
        state = make_state([make_document(), make_document()])
        result = ReaderNode(FakeReader(), publisher).execute(state)

        self.assertEqual(len(result["analyses"]), 2)
        kinds = [item[0] for item in publisher.private]
        self.assertEqual(kinds.count(TaskEventType.READER_ITEM_STARTED), 2)
        self.assertEqual(kinds.count(TaskEventType.READER_ITEM_SUCCEEDED), 2)
        self.assertEqual(kinds[-1], TaskEventType.READER_STAGE_COMPLETED)
        stage = publisher.private[-1][1]
        self.assertEqual((stage["completed"], stage["succeeded"], stage["failed"]), (2, 2, 0))

    def test_item_failure_isolated_and_counts_are_consistent(self):
        documents = [make_document(), make_document(), make_document()]
        publisher = CapturingPublisher()
        result = ReaderNode(FakeReader({documents[1].paper_id}), publisher).execute(
            make_state(documents)
        )

        self.assertEqual(len(result["analyses"]), 2)
        failures = [item for item in publisher.private if item[0] is TaskEventType.READER_ITEM_FAILED]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][1]["failure_category"], "STRUCTURED_OUTPUT_PARSE")
        self.assertGreaterEqual(failures[0][1]["page_count"], 1)
        self.assertGreater(failures[0][1]["parsed_text_char_count"], 0)
        stage = publisher.private[-1][1]
        self.assertEqual(stage["stage_outcome"], "completed")
        self.assertEqual((stage["completed"], stage["succeeded"], stage["failed"]), (3, 2, 1))

    def test_unexpected_boundary_exception_emits_stage_aborted_and_reraises(self):
        class Publisher(CapturingPublisher):
            def publish(self, run_id, event_type, payload):
                if event_type is TaskEventType.PAPER_READING_PROGRESS:
                    raise KeyboardInterrupt()
                super().publish(run_id, event_type, payload)

        publisher = Publisher()
        with self.assertRaises(KeyboardInterrupt):
            ReaderNode(FakeReader(), publisher).execute(make_state([make_document()]))
        self.assertEqual(publisher.private[-1][0], TaskEventType.READER_STAGE_ABORTED)

    def test_sanitizer_classifies_nested_failure_without_message(self):
        error = AnalysisLLMResponseError("prompt=secret raw response").with_traceback(None)
        result = sanitize_reader_exception(error)
        self.assertEqual(result["failure_category"], "STRUCTURED_OUTPUT_PARSE")
        self.assertNotIn("secret", str(result))

    def test_sanitizer_categories_are_deterministic(self):
        cases = [
            (TimeoutError(), "PROVIDER_TIMEOUT"),
            (ConnectionError(), "PROVIDER_CONNECTION"),
            (ValueError("invalid JSON"), "UNKNOWN"),
        ]
        for error, expected in cases:
            self.assertEqual(sanitize_reader_exception(error)["failure_category"], expected)

        class RateLimitError(RuntimeError):
            pass

        class AuthenticationError(RuntimeError):
            pass

        class ContextLengthError(RuntimeError):
            pass

        self.assertEqual(sanitize_reader_exception(RateLimitError())["failure_category"], "PROVIDER_RATE_LIMIT")
        self.assertEqual(sanitize_reader_exception(AuthenticationError())["failure_category"], "PROVIDER_AUTH")
        self.assertEqual(sanitize_reader_exception(ContextLengthError())["failure_category"], "CONTEXT_LENGTH")
        try:
            class RequiredField(BaseModel):
                value: int

            RequiredField.model_validate({})
        except ValidationError as error:
            self.assertEqual(sanitize_reader_exception(error)["failure_category"], "SCHEMA_VALIDATION")
        try:
            json.loads("not json")
        except json.JSONDecodeError as error:
            self.assertEqual(sanitize_reader_exception(error)["failure_category"], "STRUCTURED_OUTPUT_PARSE")

    def test_telemetry_failure_does_not_change_reader_result(self):
        class FailingPublisher(CapturingPublisher):
            def publish_diagnostic(self, *args, **kwargs):
                raise OSError("diagnostic sink unavailable")

        document = make_document()
        state = make_state([document])
        result = ReaderNode(FakeReader(), FailingPublisher()).execute(state)
        self.assertEqual(len(result["analyses"]), 1)

    def test_public_projection_hides_private_failure_details(self):
        publisher = CapturingPublisher()
        document = make_document()
        result = ReaderNode(FakeReader({document.paper_id}), publisher).execute(make_state([document]))
        failure = next(item for item in publisher.private if item[0] is TaskEventType.READER_ITEM_FAILED)
        serialized = str(failure)
        self.assertNotIn("raw response", serialized)
        self.assertNotIn(str(document.paper_id), serialized)
        self.assertEqual(result["current_step"], ResearchStep.READING)

    def test_diagnostic_payload_has_no_identifiers_or_full_text(self):
        publisher = CapturingPublisher()
        document = make_document()
        ReaderNode(FakeReader({document.paper_id}), publisher).execute(make_state([document]))
        failure = next(item[1] for item in publisher.private if item[0] is TaskEventType.READER_ITEM_FAILED)
        forbidden = {"paper_id", "evidence_id", "statement_key", "prompt", "raw_response", "full_text"}
        self.assertTrue(forbidden.isdisjoint(failure))
        self.assertNotIn("Dynamic objects degrade", str(failure))

    def test_diagnostic_summary_is_content_free(self):
        publisher = CapturingPublisher()
        document = make_document()
        ReaderNode(FakeReader({document.paper_id}), publisher).execute(make_state([document]))
        events = [
            {"event_type": event_type.value, "duration_ms": kwargs.get("duration_ms"), "diagnostic": payload}
            for event_type, payload, kwargs in publisher.private
        ]
        summary = summarize_reader_diagnostics(events)
        self.assertEqual(summary["failure_categories"], {"STRUCTURED_OUTPUT_PARSE": 1})
        self.assertEqual(summary["stage_outcome"], "completed")
        self.assertNotIn(str(document.paper_id), str(summary))

    def test_item_index_is_one_based_and_ordered(self):
        publisher = CapturingPublisher()
        ReaderNode(FakeReader(), publisher).execute(make_state([make_document(), make_document()]))
        started = [item[1]["item_index"] for item in publisher.private if item[0] is TaskEventType.READER_ITEM_STARTED]
        self.assertEqual(started, [1, 2])

    def test_stage_abort_reports_partial_counts(self):
        class AbortPublisher(CapturingPublisher):
            def publish(self, run_id, event_type, payload):
                if event_type is TaskEventType.PAPER_READING_PROGRESS and payload.completed == 1:
                    raise RuntimeError("sink failure")
                super().publish(run_id, event_type, payload)

        publisher = AbortPublisher()
        result = ReaderNode(FakeReader(), publisher).execute(
            make_state([make_document(), make_document()])
        )
        aborted = publisher.private[-1][1]
        self.assertEqual(aborted["stage_outcome"], "aborted")
        self.assertEqual(aborted["completed"], 1)
        self.assertEqual(result["current_step"], ResearchStep.READING)

    def test_broker_keeps_diagnostic_payload_private(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = SQLiteHostBroker(Path(directory) / "runtime.sqlite3")
            task_id = uuid4()
            broker.record_diagnostic_event(
                task_id,
                TaskEventType.READER_ITEM_FAILED,
                __import__("paperguide.application", fromlist=["ResearchTaskStatus"]).ResearchTaskStatus.RUNNING,
                {"failure_category": "SCHEMA_VALIDATION", "safe_title_preview": "A" * 200},
            )
            public = broker.list_events(task_id)
            private = broker.list_diagnostic_events(task_id)
        self.assertEqual(public, [])
        self.assertEqual(private[0]["diagnostic"]["safe_title_preview"], "A" * 100)


if __name__ == "__main__":
    unittest.main()
