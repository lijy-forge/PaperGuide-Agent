"""P0 public progress persistence and safety tests."""

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from paperpilot.application import ResearchTaskStatus
from paperpilot.progress.events import TaskEventType
from paperpilot.progress.models import ProgressEventPayload, ProgressStage
from paperpilot.progress.publisher import ProgressPublisher
from paperpilot.progress.timing import summarize_progress_timing
from paperpilot.progress.validator import PublicProgressValidator
from paperpilot.runtime.host import SQLiteHostBroker


class ProgressTests(unittest.TestCase):
    def test_persisted_progress_is_ordered_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            broker = SQLiteHostBroker(path)
            task_id, run_id = uuid4(), uuid4()
            publisher = ProgressPublisher(broker)
            publisher.bind(run_id, task_id)
            started = ProgressEventPayload(stage=ProgressStage.PDF_PROCESSING, completed=0, total=2, succeeded=0, failed=0, skipped=0)
            progressed = ProgressEventPayload(stage=ProgressStage.PDF_PROCESSING, completed=1, total=2, succeeded=1, failed=0, skipped=0, paper_title_preview="A public paper title")
            publisher.publish(run_id, TaskEventType.PDF_PROCESSING_STARTED, started)
            publisher.publish(run_id, TaskEventType.PDF_PROCESSING_PROGRESS, progressed)
            publisher.publish(run_id, TaskEventType.PDF_PROCESSING_PROGRESS, progressed)
            events = SQLiteHostBroker(path).list_events(task_id)
            metrics = publisher.append_metrics()
        self.assertEqual([event.event_id for event in events], sorted(event.event_id for event in events))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1].progress.completed, 1)
        self.assertEqual(metrics.count, 3)
        self.assertGreaterEqual(metrics.p95_latency_ms, 0)

    def test_public_validator_rejects_internal_content(self) -> None:
        validator = PublicProgressValidator()
        with self.assertRaises(ValueError):
            validator.validate(ProgressEventPayload(stage=ProgressStage.PAPER_READING, message="api_key=secret"))
        with self.assertRaises(ValueError):
            validator.validate(ProgressEventPayload(stage=ProgressStage.PAPER_READING, paper_title_preview="C:/private/report.pdf"))

    def test_public_title_preview_is_truncated(self) -> None:
        payload = ProgressEventPayload(
            stage=ProgressStage.PAPER_READING,
            paper_title_preview="A" * 180,
        )
        self.assertEqual(payload.paper_title_preview, "A" * 100)

    def test_counts_and_timing_are_deterministic(self) -> None:
        with self.assertRaises(ValueError):
            ProgressEventPayload(stage=ProgressStage.PDF_PROCESSING, completed=2, total=3, succeeded=1, failed=0, skipped=0)
        with tempfile.TemporaryDirectory() as directory:
            broker = SQLiteHostBroker(Path(directory) / "runtime.sqlite3")
            task_id, run_id = uuid4(), uuid4()
            publisher = ProgressPublisher(broker)
            publisher.bind(run_id, task_id)
            publisher.publish(run_id, TaskEventType.RETRIEVAL_STARTED, ProgressEventPayload(stage=ProgressStage.RETRIEVAL))
            publisher.publish(run_id, TaskEventType.RETRIEVAL_COMPLETED, ProgressEventPayload(stage=ProgressStage.RETRIEVAL, completed=1, total=1))
            summary = summarize_progress_timing(broker.list_events(task_id))
        self.assertIn(ProgressStage.RETRIEVAL, summary.stage_ms)

    def test_publish_failure_is_non_fatal(self) -> None:
        class FailingBroker:
            def record_progress_event(self, *args, **kwargs):
                raise OSError("sqlite temporarily unavailable")

        publisher = ProgressPublisher(FailingBroker())
        run_id = uuid4()
        publisher.bind(run_id, uuid4())
        publisher.publish(
            run_id,
            TaskEventType.QUERY_PLANNING_STARTED,
            ProgressEventPayload(stage=ProgressStage.QUERY_PLANNING),
        )
        self.assertEqual(publisher.append_metrics().count, 0)

    def test_persisted_history_survives_reopen_with_partial_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            task_id, run_id = uuid4(), uuid4()
            publisher = ProgressPublisher(SQLiteHostBroker(path))
            publisher.bind(run_id, task_id)
            for event_type, stage in (
                (TaskEventType.QUERY_PLANNING_STARTED, ProgressStage.QUERY_PLANNING),
                (TaskEventType.QUERY_PLANNING_COMPLETED, ProgressStage.QUERY_PLANNING),
                (TaskEventType.RETRIEVAL_STARTED, ProgressStage.RETRIEVAL),
                (TaskEventType.RETRIEVAL_COMPLETED, ProgressStage.RETRIEVAL),
                (TaskEventType.METADATA_FILTERING_STARTED, ProgressStage.METADATA_FILTERING),
                (TaskEventType.METADATA_FILTERING_COMPLETED, ProgressStage.METADATA_FILTERING),
                (TaskEventType.PDF_PROCESSING_STARTED, ProgressStage.PDF_PROCESSING),
                (TaskEventType.PDF_PROCESSING_COMPLETED, ProgressStage.PDF_PROCESSING),
                (TaskEventType.PAPER_READING_STARTED, ProgressStage.PAPER_READING),
                (TaskEventType.PAPER_READING_COMPLETED, ProgressStage.PAPER_READING),
                (TaskEventType.EVIDENCE_VERIFICATION_STARTED, ProgressStage.EVIDENCE_VERIFICATION),
                (TaskEventType.EVIDENCE_VERIFICATION_COMPLETED, ProgressStage.EVIDENCE_VERIFICATION),
                (TaskEventType.FINAL_RELEVANCE_STARTED, ProgressStage.FINAL_RELEVANCE),
                (TaskEventType.FINAL_RELEVANCE_COMPLETED, ProgressStage.FINAL_RELEVANCE),
                (TaskEventType.SURVEY_SYNTHESIS_STARTED, ProgressStage.SURVEY_SYNTHESIS),
                (TaskEventType.SURVEY_SYNTHESIS_COMPLETED, ProgressStage.SURVEY_SYNTHESIS),
                (TaskEventType.ARTIFACT_EXPORT_STARTED, ProgressStage.ARTIFACT_EXPORT),
                (TaskEventType.ARTIFACT_EXPORT_COMPLETED, ProgressStage.ARTIFACT_EXPORT),
            ):
                terminal = event_type.value.endswith("_completed")
                if stage in {ProgressStage.PDF_PROCESSING, ProgressStage.PAPER_READING, ProgressStage.EVIDENCE_VERIFICATION}:
                    payload = ProgressEventPayload(
                        stage=stage,
                        completed=5 if terminal else 0,
                        total=5,
                        succeeded=4 if terminal else 0,
                        failed=1 if terminal else 0,
                        skipped=0,
                    )
                else:
                    payload = ProgressEventPayload(stage=stage)
                publisher.publish(run_id, event_type, payload)

            reopened = SQLiteHostBroker(path).list_events(task_id)
        stages = {event.progress.stage for event in reopened if event.progress}
        self.assertEqual(stages, set(ProgressStage))
        reading = next(event for event in reopened if event.event_type is TaskEventType.PAPER_READING_COMPLETED)
        self.assertEqual((reading.progress.succeeded, reading.progress.failed, reading.progress.skipped), (4, 1, 0))


if __name__ == "__main__":
    unittest.main()
