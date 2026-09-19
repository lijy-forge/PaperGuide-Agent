"""Dependency-injected application entry point for complete research runs."""

import inspect
import re
from collections.abc import Sequence
from copy import deepcopy
from typing import Protocol
from uuid import UUID

from paperguide.domain import PaperSource, ResearchConfig
from paperguide.export import ExportFormat, ExportResult
from paperguide.orchestration import (
    NextAction,
    ResearchState,
    ResearchStep,
    create_initial_state,
    validate_state,
)
from paperguide.orchestration.errors import sanitize_message
from paperguide.progress.events import TaskEventType
from paperguide.progress.models import ProgressEventPayload, ProgressStage
from paperguide.progress.publisher import ProgressPublisherProtocol
from paperguide.relevance import ReportMode
from paperguide.reporting import ResearchReport, SurveyReport
from paperguide.reporting.survey_telemetry import SurveyTelemetry
from paperguide.verification import VerifiedPaperAnalysisResult

from .exceptions import ApplicationError, ResearchExecutionError
from .models import (
    ReportQualityStatus,
    ResearchRequest,
    ResearchResult,
    ResearchTask,
    ResearchTaskStatus,
)
from .report_quality import ReportQualityContract
from .source_probe import SourceProbeProtocol
from .store import TaskStoreProtocol


class ResearchGraphProtocol(Protocol):
    """Synchronous compiled-graph boundary used by the application service."""

    def invoke(self, state: ResearchState) -> ResearchState:
        """Execute one complete research graph run."""

        ...


class ReportGeneratorProtocol(Protocol):
    """Generate an evidence-grounded report from verified paper results."""

    def generate(
        self,
        question: str,
        verified_results: list[VerifiedPaperAnalysisResult],
    ) -> ResearchReport:
        """Return one validated research report."""

        ...


class SurveyReportGeneratorProtocol(Protocol):
    """Generate the production SurveyReport from one completed graph state."""

    def generate(self, state: ResearchState) -> SurveyReport:
        ...


class ReportExportServiceProtocol(Protocol):
    """Export one report in a requested format."""

    def export(
        self,
        report: ResearchReport | SurveyReport,
        export_format: ExportFormat,
    ) -> ExportResult:
        """Return an export result containing artifact metadata."""

        ...


class ResearchApplicationService:
    """Coordinate graph, report generation, export, and task lifecycle."""

    def __init__(
        self,
        graph: ResearchGraphProtocol,
        report_generator: ReportGeneratorProtocol,
        export_service: ReportExportServiceProtocol,
        task_store: TaskStoreProtocol,
        *,
        survey_report_generator: SurveyReportGeneratorProtocol | None = None,
        progress_publisher: ProgressPublisherProtocol | None = None,
        report_quality_contract: ReportQualityContract | None = None,
        sources: Sequence[PaperSource] | None = None,
        source_probe: SourceProbeProtocol | None = None,
    ) -> None:
        self.graph = graph
        self.report_generator = report_generator
        self.export_service = export_service
        self.task_store = task_store
        self.survey_report_generator = survey_report_generator
        self.progress_publisher = progress_publisher
        self.report_quality_contract = report_quality_contract or ReportQualityContract()
        # Optional, because the offline demo and every test double retrieve
        # without a network and have nothing to probe.
        self.source_probe = source_probe
        self.sources = tuple(
            sources
            if sources is not None
            else (PaperSource.ARXIV, PaperSource.SEMANTIC_SCHOLAR)
        )
        if not self.sources:
            raise ValueError("application service requires at least one paper source")

    def run(self, request: ResearchRequest, *, task_id: UUID | None = None) -> ResearchResult:
        """Create and synchronously execute one complete research task."""

        start_year, end_year = self._infer_year_range(request.question)
        config = ResearchConfig(
            question=request.question,
            start_year=start_year,
            end_year=end_year,
            max_papers=request.max_papers,
            sources=list(self.sources),
            manual_sources=list(request.manual_sources),
        )
        initial_state = create_initial_state(request.question, config)
        if task_id is None:
            task = self.task_store.save(
                ResearchTask(
                    run_id=initial_state["run_id"],
                    question=request.question,
                )
            )
        else:
            task = self.task_store.get(task_id)
            if task.question != request.question:
                raise ApplicationError("existing task does not match the request")
            initial_state["run_id"] = task.run_id
        self.task_store.update(task.task_id, status=ResearchTaskStatus.RUNNING)
        if self.progress_publisher is not None:
            self.progress_publisher.bind(initial_state["run_id"], task.task_id)

        # Before the graph, because its first node plans queries with the
        # model: starting a run that cannot retrieve anything would pay for
        # that call and then fail with nothing to show for it.
        unavailable = self._refuse_when_no_source_answers(task)
        if unavailable is not None:
            return unavailable

        try:
            graph_output = self.graph.invoke(deepcopy(initial_state))
            final_state = validate_state(graph_output)
            if (
                self.survey_report_generator is not None
                and self._is_survey_terminal_state(final_state)
            ):
                self._publish(initial_state, TaskEventType.SURVEY_SYNTHESIS_STARTED, ProgressEventPayload(stage=ProgressStage.SURVEY_SYNTHESIS))
                telemetry = self._survey_telemetry(final_state)
                generator = self.survey_report_generator.generate
                if "telemetry" in inspect.signature(generator).parameters:
                    report = generator(deepcopy(final_state), telemetry=telemetry)
                else:
                    report = generator(deepcopy(final_state))
                self._publish(final_state, TaskEventType.SURVEY_SYNTHESIS_COMPLETED, ProgressEventPayload(stage=ProgressStage.SURVEY_SYNTHESIS, message=self._report_mode_message(final_state)))
            else:
                terminal_result = self._terminal_result(task, final_state)
                if terminal_result is not None:
                    return terminal_result
                verified_results = list(final_state["verified_results"].values())
                report = self.report_generator.generate(
                    request.question,
                    deepcopy(verified_results),
                )
            quality = self.report_quality_contract.assess(report)
            self._publish_quality_diagnostic(final_state, quality)
            if not quality.accepted:
                # A report with no references at all failed for a reason the
                # reader can act on — nothing survived retrieval and filtering —
                # whereas the general code says only that some contract was
                # broken. Reported separately so the interface can say which.
                rejected = self.task_store.update(
                    task.task_id,
                    status=ResearchTaskStatus.FAILED,
                    report_quality_status=ReportQualityStatus.REJECTED,
                    artifact=None,
                    error=self._rejection_code(quality, final_state),
                )
                return ResearchResult(task=rejected, report=report.model_copy(deep=True))
            self._publish(final_state, TaskEventType.ARTIFACT_EXPORT_STARTED, ProgressEventPayload(stage=ProgressStage.ARTIFACT_EXPORT))
            export_result = self.export_service.export(
                report.model_copy(deep=True),
                request.export_format,
            )
            if export_result.artifact is None:
                raise ApplicationError("export service returned no artifact metadata")
            self._publish(final_state, TaskEventType.ARTIFACT_EXPORT_COMPLETED, ProgressEventPayload(stage=ProgressStage.ARTIFACT_EXPORT, message=request.export_format.value.upper()))
            completed = self.task_store.update(
                task.task_id,
                status=ResearchTaskStatus.COMPLETED,
                report_quality_status=ReportQualityStatus.ACCEPTED,
                artifact=export_result.artifact,
                error=None,
            )
            return ResearchResult(
                task=completed,
                report=report.model_copy(deep=True),
                export_result=export_result.model_copy(deep=True),
            )
        except Exception as error:
            message = sanitize_message(str(error) or type(error).__name__)
            self.task_store.update(
                task.task_id,
                status=ResearchTaskStatus.FAILED,
                artifact=None,
                error=message,
            )
            raise ResearchExecutionError(
                "research task execution failed",
                task_id=task.task_id,
                run_id=task.run_id,
            ) from error
        finally:
            if self.progress_publisher is not None:
                self.progress_publisher.unbind(initial_state["run_id"])

    def _publish(self, state: ResearchState, event_type: TaskEventType, payload: ProgressEventPayload) -> None:
        if self.progress_publisher is not None:
            self.progress_publisher.publish(state["run_id"], event_type, payload)

    def _publish_quality_diagnostic(self, state: ResearchState, quality) -> None:
        """Persist scalar-only private funnel data without affecting execution."""

        publish = getattr(self.progress_publisher, "publish_diagnostic", None)
        if publish is None:
            return
        analyses = state.get("analyses", {})
        verification = state.get("verification_results", {})
        final = state.get("final_relevance", {})
        page_present = page_missing = input_count = accepted = rejected = 0
        for result in verification.values():
            input_count += result.total_evidence
            accepted += result.total_verified + result.total_partial
            rejected += result.total_rejected + result.total_conflicted
            for item in result.verified_evidence:
                if item.status.value in {"verified", "partially_supported"}:
                    if item.evidence.locator.page_start is None:
                        page_missing += 1
                    else:
                        page_present += 1
        names = [getattr(getattr(item, "final_classification", None), "value", None) for item in final.values()]
        text_lengths = [sum(len(page.text) for page in document.pages) for document in state.get("documents", {}).values()]
        sorted_lengths = sorted(text_lengths)
        midpoint = len(sorted_lengths) // 2
        median_length = (
            0 if not sorted_lengths else
            sorted_lengths[midpoint] if len(sorted_lengths) % 2 else
            (sorted_lengths[midpoint - 1] + sorted_lengths[midpoint]) // 2
        )
        payload = {
            "reader_input_papers": len(state.get("documents", {})),
            "reader_succeeded_papers": len(analyses),
            "reader_failed_papers": sum(error.stage.value == "reading" for error in state.get("errors", [])),
            "reader_statement_total": sum(len(item.evidence) for item in analyses.values()),
            "pdf_success_count": len(state.get("documents", {})),
            "reader_text_available_count": sum(bool(item.pages) for item in state.get("documents", {}).values()),
            "extracted_text_char_min": min(text_lengths, default=0),
            "extracted_text_char_median": median_length,
            "extracted_text_char_max": max(text_lengths, default=0),
            "verification_input_count": input_count,
            "verification_attempted_count": input_count,
            "verification_succeeded_count": accepted,
            "verification_failed_count": rejected,
            "verified_statement_count": accepted,
            "unsupported_statement_count": rejected,
            "verified_with_page_locator": page_present,
            "verified_without_page_locator": page_missing,
            "final_core_count": names.count("core"),
            "final_adjacent_count": names.count("adjacent"),
            "final_rejected_count": names.count("rejected"),
            "citation_registry_eligible_count": quality.citation_registry_count,
            "citation_registry_registered_count": quality.citation_registry_count,
            "public_citation_count": quality.public_citation_count,
            "reference_entry_count": quality.reference_entry_count,
            "survey_evidence_paper_count": len(state.get("evidence_linked_analysis", {})),
            "survey_evidence_statement_count": quality.citation_capable_statement_count,
            "report_quality_accepted": quality.accepted,
        }
        try:
            publish(state["run_id"], TaskEventType.REPORT_QUALITY_ASSESSED, payload, dedupe_key="report-quality:assessed")
        except Exception:
            return

    def _refuse_when_no_source_answers(self, task: ResearchTask) -> ResearchResult | None:
        """Fail the task before any model call when every source refuses."""

        if self.source_probe is None:
            return None
        availability = self.source_probe.check()
        if availability.any_available:
            return None
        failed = self.task_store.update(
            task.task_id,
            status=ResearchTaskStatus.FAILED,
            artifact=None,
            error="NO_SOURCE_AVAILABLE",
        )
        return ResearchResult(task=failed, report=None)

    @staticmethod
    def _rejection_code(quality: object, state: ResearchState) -> str:
        """Name why a report was rejected, as specifically as the run allows.

        A rejection with no references at all failed for a reason the reader
        can act on, and the general code says only that some contract broke.
        Where retrieval reported that the year scope emptied the results, that
        is the most specific answer available: the query was fine and the range
        was not, which is not something a reader guesses from "no evidence".
        """

        from paperguide.pipeline.search_pipeline import PaperSearchPipeline

        if getattr(quality, "reference_entry_count", 0) != 0:
            return "REPORT_QUALITY_REJECTED"
        warnings = state.get("warnings") or []
        if PaperSearchPipeline.YEAR_SCOPE_EXCLUDED_ALL in warnings:
            return "NO_PAPERS_IN_TIME_RANGE"
        return "NO_EVIDENCE_FOR_QUESTION"

    def _survey_telemetry(self, state: ResearchState) -> SurveyTelemetry:
        """Create a private best-effort observer without changing survey control flow."""

        def publish(event_type: TaskEventType, payload: dict[str, object], duration_ms: float | None) -> None:
            reporter = getattr(self.progress_publisher, "publish_diagnostic", None)
            if reporter is not None:
                reporter(
                    state["run_id"],
                    event_type,
                    payload,
                    duration_ms=duration_ms,
                )

        return SurveyTelemetry(publish)

    @staticmethod
    def _report_mode_message(state: ResearchState) -> str | None:
        return {
            ReportMode.FULL_SURVEY: "完整综述",
            ReportMode.EVIDENCE_LIMITED_REVIEW: "证据有限综述",
        }.get(state.get("report_mode"))

    @staticmethod
    def _is_survey_terminal_state(state: ResearchState) -> bool:
        """Return whether a normal survey-mode terminal state may be rendered.

        Quality-gate ``ABORT`` is retained for insufficient evidence.  Once the
        verifier has selected a public Survey report mode, that outcome is
        renderable rather than a legacy execution failure.  Actual node
        failures and total retrieval failures remain on the existing failure
        path.
        """

        mode = state.get("report_mode")
        if mode not in {
            ReportMode.FULL_SURVEY,
            ReportMode.EVIDENCE_LIMITED_REVIEW,
        }:
            return False
        if state["current_step"] is ResearchStep.FAILED:
            return False

        errors = state.get("errors", [])
        if any(not item.recoverable for item in errors):
            return False

        # A search with no usable papers and recorded source failures is an
        # execution failure, not an evidence-limited literature outcome.
        return not (
            not state.get("papers")
            and any(item.stage is ResearchStep.RETRIEVAL for item in errors)
        )

    def get_task(self, task_id: UUID) -> ResearchTask:
        """Return an isolated task snapshot from the injected store."""

        return self.task_store.get(task_id)

    def delete_task(self, task_id: UUID) -> bool:
        """Delete a task from the injected store."""

        return self.task_store.delete(task_id)

    def _terminal_result(
        self,
        task: ResearchTask,
        state: ResearchState,
    ) -> ResearchResult | None:
        action = state["next_action"]
        if action is NextAction.HUMAN_REVIEW:
            review_task = self.task_store.update(
                task.task_id,
                status=ResearchTaskStatus.HUMAN_REVIEW,
                artifact=None,
                error=None,
            )
            return ResearchResult(task=review_task)
        if action is NextAction.ABORT or state["current_step"] is ResearchStep.FAILED:
            error_summary = ", ".join(
                f"{item.stage.value}:{item.error_type}:{sanitize_message(item.message)}"
                for item in state.get("errors", [])
            )
            detail = f" ({error_summary})" if error_summary else ""
            raise ApplicationError(
                f"research graph terminated without a report{detail}"
            )
        if action not in (NextAction.COMPLETE, NextAction.COMPLETE_DEGRADED):
            raise ApplicationError(
                f"research graph returned nonterminal action {action.value!r}"
            )
        return None

    @staticmethod
    def _infer_year_range(question: str) -> tuple[int | None, int | None]:
        """Infer an explicit year scope without using an LLM."""

        years = [
            int(value)
            for value in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", question)
        ]
        if not years:
            return None, None
        return min(years), max(years)
