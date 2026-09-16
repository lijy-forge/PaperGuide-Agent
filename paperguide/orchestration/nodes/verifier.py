"""Per-paper node adapter over EvidenceVerifier and apply_verification."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from paperguide.analysis import EvidenceLinkingService, PaperAnalysisResult
from paperguide.verification import (
    EvidenceVerificationResult,
    EvidenceVerifier,
    VerifiedPaperAnalysisResult,
    apply_verification,
)
from paperguide.orchestration.enums import NextAction, ResearchStep
from paperguide.orchestration.state import ResearchState
from paperguide.orchestration.concurrency import LLMCallLimiter
from paperguide.relevance import (
    AssessmentStatus,
    EvidenceAwareFinalRelevanceService,
    FinalCoreSelectionPolicy,
    FinalRelevanceAudit,
    FinalRelevanceClassification,
    PreliminaryRelevanceClassification,
)
from paperguide.progress.models import ProgressEventPayload, ProgressStage
from paperguide.progress.publisher import ProgressPublisherProtocol
from paperguide.progress.events import TaskEventType

from .base import BaseNode

ApplyVerification = Callable[
    [PaperAnalysisResult, EvidenceVerificationResult], VerifiedPaperAnalysisResult
]


class VerifierNode(BaseNode):
    """Verify unprocessed analyses and retain raw results when filtering fails."""

    name = "verifier"
    error_step = ResearchStep.VERIFICATION
    error_next_action = NextAction.EVALUATE_QUALITY
    error_recoverable = True

    def __init__(
        self,
        verifier: EvidenceVerifier,
        apply_verification_fn: ApplyVerification = apply_verification,
        final_relevance_service: EvidenceAwareFinalRelevanceService | None = None,
        evidence_linking_service: EvidenceLinkingService | None = None,
        progress_publisher: ProgressPublisherProtocol | None = None,
        *,
        max_concurrency: int = 1,
        llm_limiter: LLMCallLimiter | None = None,
    ):
        self.verifier = verifier
        self.apply_verification_fn = apply_verification_fn
        self.final_relevance_service = final_relevance_service
        self.evidence_linking_service = evidence_linking_service
        self.progress_publisher = progress_publisher
        self.max_concurrency = max_concurrency
        self.llm_limiter = llm_limiter

    def _execute(self, state: ResearchState) -> ResearchState:
        verification_results = dict(state.get("verification_results", {}))
        verified_results = dict(state.get("verified_results", {}))
        documents = state.get("documents", {})
        pending = [item for item in state.get("analyses", {}).items() if item[0] not in verified_results]
        total = len(pending)
        succeeded = failed = 0
        if total:
            self._publish(state, TaskEventType.EVIDENCE_VERIFICATION_STARTED, ProgressEventPayload(stage=ProgressStage.EVIDENCE_VERIFICATION, completed=0, total=total, succeeded=0, failed=0, skipped=0))
        # Only the LLM-backed verification is parallel.  Applying results and
        # mutating the state remain in source order for stable citations.
        verification_errors: dict[str, Exception] = {}
        to_verify = [
            (key, analysis, documents[key])
            for key, analysis in pending
            if key in documents and key not in verification_results
        ]
        if to_verify:
            with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
                futures = {
                    executor.submit(self._verify, analysis, document): key
                    for key, analysis, document in to_verify
                }
                completed: dict[str, EvidenceVerificationResult] = {}
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        completed[key] = future.result()
                    except Exception as error:
                        verification_errors[key] = error
                verification_results.update(
                    {key: completed[key] for key, _ in pending if key in completed}
                )
        for key, analysis in state.get("analyses", {}).items():
            if key in verified_results:
                continue
            document = documents.get(key)
            if document is None:
                state = self.add_error(
                    state,
                    stage=ResearchStep.VERIFICATION,
                    paper_id=analysis.paper_id,
                    recoverable=False,
                    error_type="MissingDocumentError",
                    message="analysis has no corresponding document",
                )
                failed += 1
                self._publish_progress(state, total, succeeded, failed, analysis)
                continue
            verification = verification_results.get(key)
            if verification is None:
                error = verification_errors.get(key)
                if error is not None:
                    failed += 1
                    state = self.add_error(state, error=error, stage=ResearchStep.VERIFICATION, paper_id=analysis.paper_id, recoverable=True)
                    self._publish_progress(state, total, succeeded, failed, analysis)
                    continue
            try:
                verified_results[key] = self.apply_verification_fn(
                    analysis, verification
                )
                succeeded += 1
            except Exception as error:
                failed += 1
                state = self.add_error(
                    state,
                    error=error,
                    stage=ResearchStep.VERIFICATION,
                    paper_id=analysis.paper_id,
                    # Filtering one paper's verified evidence is an item-level
                    # operation.  Other papers can still provide sufficient
                    # input for an evidence-limited Survey, so preserve this
                    # failure in state without escalating it to task-fatal.
                    recoverable=True,
                )
            self._publish_progress(state, total, succeeded, failed, analysis)
        state["verification_results"] = verification_results
        state["verified_results"] = verified_results
        if self.evidence_linking_service is not None:
            papers_by_id = {paper.id: paper for paper in state.get("papers", [])}
            linked_results = dict(state.get("evidence_linked_analysis", {}))
            for key, verified in verified_results.items():
                analysis = state.get("analyses", {}).get(key)
                if analysis is None:
                    continue
                try:
                    linked_results[key] = self.evidence_linking_service.link(
                        analysis, verified, papers_by_id.get(analysis.paper_id)
                    )
                except Exception:
                    state.setdefault("warnings", []).append("STATEMENT_LINKING_INCOMPLETE")
            state["evidence_linked_analysis"] = linked_results
        if self.final_relevance_service is not None:
            self._publish(state, TaskEventType.FINAL_RELEVANCE_STARTED, ProgressEventPayload(stage=ProgressStage.FINAL_RELEVANCE))
            papers_by_id = {paper.id: paper for paper in state.get("papers", [])}
            preliminary_by_id = {
                record.paper_id: record.classification
                for record in state.get("candidate_relevance", [])
            }
            assessments = []
            for paper_id, paper in papers_by_id.items():
                analysis = state.get("analyses", {}).get(str(paper_id))
                verified = verified_results.get(str(paper_id))
                assessments.append(
                    self.final_relevance_service.assess(
                        paper,
                        analysis,
                        verified,
                        self._intent_from_state(state),
                        preliminary_by_id.get(paper_id),
                    )
                )
            selected, not_selected = FinalCoreSelectionPolicy().select(
                assessments,
                papers_by_id,
                state["research_config"].max_papers,
            )
            selected_set = set(selected)
            assessments = [
                item.model_copy(update={"selected_for_report": item.paper_id in selected_set})
                for item in assessments
            ]
            sufficiency = self.final_relevance_service.assess_sufficiency(
                assessments,
                verified_results.values(),
                self._intent_from_state(state),
                selected_core_count=len(selected),
            )
            state["final_relevance"] = {str(item.paper_id): item for item in assessments}
            state["evidence_sufficiency"] = sufficiency
            state["report_mode"] = sufficiency.recommended_report_mode
            state["final_relevance_audit"] = FinalRelevanceAudit(
                papers_sent_to_reader=len(state.get("documents", {})),
                papers_successfully_read=len(state.get("analyses", {})),
                papers_unassessable=sum(item.assessment_status is AssessmentStatus.UNASSESSABLE for item in assessments),
                final_core_count=sum(item.final_classification is FinalRelevanceClassification.CORE for item in assessments),
                final_adjacent_count=sum(item.final_classification is FinalRelevanceClassification.ADJACENT for item in assessments),
                final_rejected_count=sum(item.final_classification is FinalRelevanceClassification.REJECTED for item in assessments),
                selected_core_count=len(selected),
                core_not_selected_count=not_selected,
                verified_evidence_count=sum(len(item.verification.verified_evidence) for item in verified_results.values()),
                recommended_report_mode=sufficiency.recommended_report_mode,
            )
            self._publish(state, TaskEventType.FINAL_RELEVANCE_COMPLETED, ProgressEventPayload(stage=ProgressStage.FINAL_RELEVANCE, completed=len(assessments), total=len(assessments), message=f"{len(selected)} core selected"))
        state["current_step"] = ResearchStep.VERIFICATION
        state["next_action"] = NextAction.EVALUATE_QUALITY
        if total:
            self._publish(state, TaskEventType.EVIDENCE_VERIFICATION_COMPLETED, ProgressEventPayload(stage=ProgressStage.EVIDENCE_VERIFICATION, completed=total, total=total, succeeded=succeeded, failed=failed, skipped=0))
        return state

    def _verify(self, analysis: PaperAnalysisResult, document):
        if self.llm_limiter is None:
            return self.verifier.verify(analysis, document)
        with self.llm_limiter:
            return self.verifier.verify(analysis, document)

    def _publish_progress(self, state: ResearchState, total: int, succeeded: int, failed: int, analysis: PaperAnalysisResult) -> None:
        self._publish(state, TaskEventType.EVIDENCE_VERIFICATION_PROGRESS, ProgressEventPayload(stage=ProgressStage.EVIDENCE_VERIFICATION, completed=succeeded + failed, total=total, succeeded=succeeded, failed=failed, skipped=0, paper_title_preview=self._title_for(state, analysis.paper_id)))

    def _publish(self, state: ResearchState, event_type: TaskEventType, payload: ProgressEventPayload) -> None:
        if self.progress_publisher is not None:
            self.progress_publisher.publish(state["run_id"], event_type, payload)

    @staticmethod
    def _title_for(state: ResearchState, paper_id) -> str | None:
        return next((paper.title for paper in state.get("papers", []) if paper.id == paper_id), None)

    @staticmethod
    def _intent_from_state(state: ResearchState):
        plan = state.get("retrieval_plan")
        if plan is not None:
            return plan.intent
        # Backward-compatible fallback for states created before retrieval planning.
        from paperguide.relevance import ResearchIntent

        return ResearchIntent(
            research_question=state["question"],
            required_concepts=[state["question"]],
        )
