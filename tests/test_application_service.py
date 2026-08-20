"""Unit tests for the dependency-injected PaperPilot application service."""

import copy
import hashlib
import unittest
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from paperpilot.application import (
    InMemoryTaskStore,
    ResearchApplicationService,
    ResearchExecutionError,
    ResearchRequest,
    ResearchTask,
    ResearchTaskStatus,
    TaskNotFoundError,
)
from paperpilot.domain import SourceLocator
from paperpilot.export import (
    ArtifactMetadata,
    ExportFormat,
    ExportResult,
)
from paperpilot.orchestration import NextAction, ResearchError, ResearchStep
from paperpilot.reporting import (
    ReportCitation,
    ReportClaim,
    ReportSection,
    ResearchReport,
)


def make_report(question: str) -> ResearchReport:
    """Create one complete evidence-grounded report."""

    paper_id = uuid4()
    evidence_id = uuid4()
    return ResearchReport(
        question=question,
        title="Application Research Report",
        summary="Verified evidence supports the result.",
        sections=[
            ReportSection(
                title="Findings",
                claims=[
                    ReportClaim(
                        text="The verified method improves accuracy.",
                        evidence_ids=[evidence_id],
                    )
                ],
                evidence_ids=[evidence_id],
            )
        ],
        citations=[
            ReportCitation(
                paper_id=paper_id,
                evidence_id=evidence_id,
                quote="The method improves accuracy.",
                locator=SourceLocator(
                    paper_id=paper_id,
                    section_title="Results",
                    page_start=3,
                    page_end=3,
                ),
            )
        ],
        evidence_ids=[evidence_id],
        warnings=[],
    )


class FakeGraph:
    """Return a selected terminal graph action or raise a configured failure."""

    def __init__(self, action=NextAction.COMPLETE, error=None):
        self.action = action
        self.error = error
        self.inputs = []

    def invoke(self, state):
        self.inputs.append(copy.deepcopy(state))
        if self.error is not None:
            raise self.error
        result = copy.deepcopy(state)
        result["current_step"] = ResearchStep.QUALITY_GATE
        result["next_action"] = self.action
        return result


class FakeReportGenerator:
    """Build a report without an LLM and record verified-result input."""

    def __init__(self, error=None):
        self.error = error
        self.calls = []
        self.last_report = None

    def generate(self, question, verified_results):
        self.calls.append((question, copy.deepcopy(verified_results)))
        if self.error is not None:
            raise self.error
        self.last_report = make_report(question)
        return self.last_report


class FakeExportService:
    """Return artifact metadata or raise without writing files."""

    def __init__(self, error=None, mutate_input=False):
        self.error = error
        self.mutate_input = mutate_input
        self.calls = []

    def export(self, report, export_format):
        self.calls.append((report.model_copy(deep=True), export_format))
        if self.error is not None:
            raise self.error
        if self.mutate_input:
            report.title = "Mutated by fake exporter"
        content = "exported report"
        file_path = str(Path(f"application-report.{export_format.value}").resolve())
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        artifact = ArtifactMetadata(
            format=export_format,
            file_path=file_path,
            size_bytes=len(content.encode("utf-8")),
            sha256=digest,
        )
        return ExportResult(
            format=export_format,
            media_type="text/plain",
            content=content,
            file_path=file_path,
            size_bytes=artifact.size_bytes,
            warnings=[],
            artifact=artifact,
        )


def make_service(graph=None, report_generator=None, export_service=None, store=None):
    """Create an application service entirely from fake dependencies."""

    return ResearchApplicationService(
        graph or FakeGraph(),
        report_generator or FakeReportGenerator(),
        export_service or FakeExportService(),
        store or InMemoryTaskStore(),
    )


class ApplicationServiceTests(unittest.TestCase):
    """Verify execution, failures, task lifecycle, validation, and isolation."""

    def test_normal_research_flow(self) -> None:
        graph = FakeGraph()
        report_generator = FakeReportGenerator()
        export_service = FakeExportService()
        store = InMemoryTaskStore()
        service = make_service(graph, report_generator, export_service, store)
        request = ResearchRequest(
            question="Analyze visual SLAM",
            max_papers=7,
            export_format=ExportFormat.HTML,
        )

        result = service.run(request)

        self.assertEqual(result.task.status, ResearchTaskStatus.COMPLETED)
        self.assertEqual(result.task.run_id, graph.inputs[0]["run_id"])
        self.assertEqual(graph.inputs[0]["research_config"].max_papers, 7)
        self.assertEqual(export_service.calls[0][1], ExportFormat.HTML)
        self.assertEqual(service.get_task(result.task.task_id), result.task)

    def test_explicit_year_range_is_inferred_for_research_config(self) -> None:
        graph = FakeGraph()
        service = make_service(graph=graph)

        service.run(
            ResearchRequest(question="Analyze YOLO SLAM research from 2024-2026")
        )

        config = graph.inputs[0]["research_config"]
        self.assertEqual(config.start_year, 2024)
        self.assertEqual(config.end_year, 2026)

    def test_graph_failure_marks_task_failed(self) -> None:
        store = InMemoryTaskStore()
        service = make_service(
            graph=FakeGraph(error=RuntimeError("graph failed")),
            store=store,
        )

        with self.assertRaises(ResearchExecutionError) as captured:
            service.run(ResearchRequest(question="Analyze SLAM"))

        task = store.get(captured.exception.task_id)
        self.assertEqual(task.status, ResearchTaskStatus.FAILED)
        self.assertIn("graph failed", task.error)

    def test_aborted_graph_reports_safe_node_error_types(self) -> None:
        class AbortedGraph(FakeGraph):
            def invoke(self, state):
                result = super().invoke(state)
                result["errors"].append(
                    ResearchError(
                        stage=ResearchStep.READING,
                        error_type="AnalysisLLMInvocationError",
                        message="provider invocation failed",
                        recoverable=True,
                        attempt=0,
                    )
                )
                return result

        store = InMemoryTaskStore()
        service = make_service(
            graph=AbortedGraph(action=NextAction.ABORT),
            store=store,
        )

        with self.assertRaises(ResearchExecutionError) as captured:
            service.run(ResearchRequest(question="Analyze SLAM"))

        task = store.get(captured.exception.task_id)
        self.assertIn("reading:AnalysisLLMInvocationError", task.error)
        self.assertIn("provider invocation failed", task.error)

    def test_export_failure_marks_task_failed(self) -> None:
        store = InMemoryTaskStore()
        service = make_service(
            export_service=FakeExportService(
                error=RuntimeError("export unavailable")
            ),
            store=store,
        )

        with self.assertRaises(ResearchExecutionError) as captured:
            service.run(ResearchRequest(question="Analyze SLAM"))

        task = store.get(captured.exception.task_id)
        self.assertEqual(task.status, ResearchTaskStatus.FAILED)
        self.assertIn("export unavailable", task.error)

    def test_human_review_state_is_returned_without_export(self) -> None:
        export_service = FakeExportService()
        result = make_service(
            graph=FakeGraph(action=NextAction.HUMAN_REVIEW),
            export_service=export_service,
        ).run(ResearchRequest(question="Analyze disputed evidence"))

        self.assertEqual(result.task.status, ResearchTaskStatus.HUMAN_REVIEW)
        self.assertIsNone(result.report)
        self.assertIsNone(result.export_result)
        self.assertEqual(export_service.calls, [])

    def test_task_query_and_delete(self) -> None:
        store = InMemoryTaskStore()
        task = store.save(ResearchTask(run_id=uuid4(), question="Question"))

        self.assertEqual(store.get(task.task_id), task)
        self.assertTrue(store.delete(task.task_id))
        self.assertFalse(store.delete(task.task_id))
        with self.assertRaises(TaskNotFoundError):
            store.get(task.task_id)

    def test_task_status_update(self) -> None:
        store = InMemoryTaskStore()
        task = store.save(ResearchTask(run_id=uuid4(), question="Question"))

        updated = store.update(task.task_id, status=ResearchTaskStatus.RUNNING)

        self.assertEqual(updated.status, ResearchTaskStatus.RUNNING)
        self.assertGreaterEqual(updated.updated_at, task.updated_at)
        self.assertEqual(store.get(task.task_id), updated)

    def test_empty_question_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ResearchRequest(question="   ")

    def test_max_papers_range_is_enforced(self) -> None:
        for value in (0, 51):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ResearchRequest(question="Question", max_papers=value)

    def test_unknown_request_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ResearchRequest(question="Question", unexpected=True)

    def test_input_and_report_objects_are_isolated(self) -> None:
        request = ResearchRequest(question="Analyze SLAM")
        original_request = request.model_copy(deep=True)
        report_generator = FakeReportGenerator()
        export_service = FakeExportService(mutate_input=True)
        service = make_service(
            report_generator=report_generator,
            export_service=export_service,
        )

        result = service.run(request)

        self.assertEqual(request, original_request)
        self.assertEqual(result.report.title, "Application Research Report")
        self.assertEqual(
            report_generator.last_report.title,
            "Application Research Report",
        )

    def test_task_store_returns_deep_copies(self) -> None:
        store = InMemoryTaskStore()
        task = store.save(ResearchTask(run_id=uuid4(), question="Question"))
        loaded = store.get(task.task_id)

        self.assertIsNot(loaded, task)
        self.assertEqual(loaded, task)


if __name__ == "__main__":
    unittest.main()
