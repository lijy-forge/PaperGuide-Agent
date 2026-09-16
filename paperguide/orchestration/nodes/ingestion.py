"""Node adapter over the existing DocumentIngestionPipeline."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from paperguide.document import DocumentIngestionPipeline, DocumentIngestionResult
from paperguide.orchestration.enums import NextAction, ResearchStep
from paperguide.orchestration.state import ResearchState
from paperguide.progress.events import TaskEventType
from paperguide.progress.models import ProgressEventPayload, ProgressStage
from paperguide.progress.publisher import ProgressPublisherProtocol

from .base import BaseNode


class IngestionNode(BaseNode):
    """Ingest only papers that do not already have a successful Document."""

    name = "ingestion"
    error_step = ResearchStep.INGESTION
    error_next_action = NextAction.EVALUATE_QUALITY
    error_recoverable = True

    def __init__(self, pipeline: DocumentIngestionPipeline, progress_publisher: ProgressPublisherProtocol | None = None, *, max_concurrency: int = 1):
        self.pipeline = pipeline
        self.progress_publisher = progress_publisher
        self.max_concurrency = max_concurrency

    def _execute(self, state: ResearchState) -> ResearchState:
        existing_documents = dict(state.get("documents", {}))
        pending = [
            paper for paper in state["papers"] if str(paper.id) not in existing_documents
        ]
        if pending:
            self._publish(state, TaskEventType.PDF_PROCESSING_STARTED, ProgressEventPayload(stage=ProgressStage.PDF_PROCESSING, completed=0, total=len(pending), succeeded=0, failed=0, skipped=0))
            if self.max_concurrency == 1:
                # Preserve legacy batch-level PDF-content reuse semantics.
                if self.progress_publisher is None:
                    result = self.pipeline.ingest(pending)
                else:
                    result = self.pipeline.ingest(pending, item_observer=lambda completed, succeeded, failed, skipped, title: self._publish(state, TaskEventType.PDF_PROCESSING_PROGRESS, ProgressEventPayload(stage=ProgressStage.PDF_PROCESSING, completed=completed, total=len(pending), succeeded=succeeded, failed=failed, skipped=skipped, paper_title_preview=title)))
            else:
                result = self._ingest_concurrently(state, pending)
            existing_documents.update(
                {str(document.paper_id): document for document in result.documents}
            )
            state["ingestion_result"] = result
            state["warnings"] = self._stable_unique(
                [*state.get("warnings", []), *result.warnings]
            )
            self._publish(state, TaskEventType.PDF_PROCESSING_COMPLETED, ProgressEventPayload(stage=ProgressStage.PDF_PROCESSING, completed=result.total_requested, total=result.total_requested, succeeded=result.total_parsed, failed=result.total_failed, skipped=result.total_skipped))
        state["documents"] = existing_documents
        state["current_step"] = ResearchStep.INGESTION
        state["next_action"] = NextAction.READ
        return state

    def _ingest_concurrently(self, state: ResearchState, papers) -> DocumentIngestionResult:
        """Process independent papers concurrently and merge in input order."""
        completed = succeeded = failed = skipped = 0
        results: dict[int, DocumentIngestionResult] = {}
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
            futures = {executor.submit(self.pipeline.ingest, [paper]): index for index, paper in enumerate(papers)}
            for future in as_completed(futures):
                index = futures[future]
                result = future.result()
                results[index] = result
                completed += 1
                succeeded += result.total_parsed
                failed += result.total_failed
                skipped += result.total_skipped
                self._publish(state, TaskEventType.PDF_PROCESSING_PROGRESS, ProgressEventPayload(stage=ProgressStage.PDF_PROCESSING, completed=completed, total=len(papers), succeeded=succeeded, failed=failed, skipped=skipped, paper_title_preview=papers[index].title))
        ordered = [results[index] for index in range(len(papers))]
        items = [item for result in ordered for item in result.items]
        documents = [document for result in ordered for document in result.documents]
        return DocumentIngestionResult(
            items=items,
            documents=documents,
            total_requested=len(items),
            total_eligible=sum(result.total_eligible for result in ordered),
            total_downloaded=sum(result.total_downloaded for result in ordered),
            total_parsed=sum(result.total_parsed for result in ordered),
            total_skipped=sum(result.total_skipped for result in ordered),
            total_failed=sum(result.total_failed for result in ordered),
            warnings=self._stable_unique([warning for result in ordered for warning in result.warnings]),
        )

    def _publish(self, state: ResearchState, event_type: TaskEventType, payload: ProgressEventPayload) -> None:
        if self.progress_publisher is not None:
            self.progress_publisher.publish(state["run_id"], event_type, payload)

    @staticmethod
    def _stable_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
