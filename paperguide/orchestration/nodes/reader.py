"""Bounded-concurrent, per-paper-isolated node adapter over PaperReader."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from time import monotonic

from paperguide.analysis import PaperReader
from paperguide.orchestration.enums import NextAction, ResearchStep
from paperguide.orchestration.state import ResearchState
from paperguide.progress.models import ProgressEventPayload, ProgressStage
from paperguide.progress.publisher import ProgressPublisherProtocol
from paperguide.progress.events import TaskEventType
from paperguide.progress.diagnostics import sanitize_reader_exception
from paperguide.orchestration.concurrency import LLMCallLimiter

from .base import BaseNode


class ReaderNode(BaseNode):
    """Analyze Documents with bounded workers and deterministic state merging."""

    name = "reader"
    error_step = ResearchStep.READING
    error_next_action = NextAction.EVALUATE_QUALITY
    error_recoverable = True

    def __init__(
        self,
        reader: PaperReader,
        progress_publisher: ProgressPublisherProtocol | None = None,
        *,
        max_concurrency: int = 1,
        llm_limiter: LLMCallLimiter | None = None,
    ):
        self.reader = reader
        self.progress_publisher = progress_publisher
        self.max_concurrency = max_concurrency
        self.llm_limiter = llm_limiter

    def _execute(self, state: ResearchState) -> ResearchState:
        analyses = dict(state.get("analyses", {}))
        pending = [item for item in state.get("documents", {}).items() if item[0] not in analyses]
        total = len(pending)
        succeeded = failed = 0
        if total:
            self._publish(state, TaskEventType.PAPER_READING_STARTED, ProgressEventPayload(stage=ProgressStage.PAPER_READING, completed=0, total=total, succeeded=0, failed=0, skipped=0))
        stage_started = monotonic()
        current_index = 0
        try:
            submitted: dict[object, tuple[int, str, object, float]] = {}
            with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
                for current_index, (key, document) in enumerate(pending, start=1):
                    item_started = monotonic()
                    self._publish_diagnostic(state, TaskEventType.READER_ITEM_STARTED, {"item_index": current_index, "total_items": total, "safe_title_preview": document.title, "page_count": len(document.pages), "parsed_text_char_count": sum(len(page.text) for page in document.pages), "outcome": "started"}, dedupe_key=f"reader:item:{current_index}:started")
                    submitted[executor.submit(self._analyze, document)] = (current_index, key, document, item_started)
                completed_results: dict[str, object] = {}
                for future in as_completed(submitted):
                    item_index, key, document, item_started = submitted[future]
                    elapsed_ms = (monotonic() - item_started) * 1000
                    try:
                        completed_results[key] = future.result()
                        succeeded += 1
                        self._publish_diagnostic(state, TaskEventType.READER_ITEM_SUCCEEDED, {"item_index": item_index, "total_items": total, "safe_title_preview": document.title, "elapsed_ms": elapsed_ms, "outcome": "success", "attempt_count": "NOT_AVAILABLE", "retry_count": "NOT_AVAILABLE"}, duration_ms=elapsed_ms, dedupe_key=f"reader:item:{item_index}:succeeded")
                    except Exception as error:
                        failed += 1
                        state = self.add_error(state, error=error, stage=ResearchStep.READING, paper_id=document.paper_id, recoverable=True)
                        diagnostic = {"item_index": item_index, "total_items": total, "safe_title_preview": document.title, "page_count": len(document.pages), "parsed_text_char_count": sum(len(page.text) for page in document.pages), "elapsed_ms": elapsed_ms, "outcome": "failure", "attempt_count": "NOT_AVAILABLE", "retry_count": "NOT_AVAILABLE", **sanitize_reader_exception(error)}
                        self._publish_diagnostic(state, TaskEventType.READER_ITEM_FAILED, diagnostic, duration_ms=elapsed_ms, dedupe_key=f"reader:item:{item_index}:failed")
                    self._publish(state, TaskEventType.PAPER_READING_PROGRESS, ProgressEventPayload(stage=ProgressStage.PAPER_READING, completed=succeeded + failed, total=total, succeeded=succeeded, failed=failed, skipped=0, paper_title_preview=document.title))
                analyses.update({key: completed_results[key] for key, _ in pending if key in completed_results})
            state["analyses"] = analyses
            state["current_step"] = ResearchStep.READING
            state["next_action"] = NextAction.VERIFY
            if total:
                self._publish(state, TaskEventType.PAPER_READING_COMPLETED, ProgressEventPayload(stage=ProgressStage.PAPER_READING, completed=total, total=total, succeeded=succeeded, failed=failed, skipped=0))
            self._publish_diagnostic(
                state,
                TaskEventType.READER_STAGE_COMPLETED,
                {
                    "completed": total,
                    "succeeded": succeeded,
                    "failed": failed,
                    "skipped": 0,
                    "stage_outcome": "completed",
                },
                duration_ms=(monotonic() - stage_started) * 1000,
                dedupe_key="reader:stage:completed",
            )
            return state
        except BaseException:
            # Preserve the original exception semantics; this event is only
            # observability and must not swallow KeyboardInterrupt/SystemExit.
            self._publish_diagnostic(
                state,
                TaskEventType.READER_STAGE_ABORTED,
                {
                    "completed": succeeded + failed,
                    "succeeded": succeeded,
                    "failed": failed,
                    "skipped": max(0, total - succeeded - failed),
                    "stage_outcome": "aborted",
                    "item_index": current_index,
                },
                duration_ms=(monotonic() - stage_started) * 1000,
                dedupe_key=f"reader:stage:aborted:{current_index}",
            )
            raise

    def _analyze(self, document):
        if self.llm_limiter is None:
            return self.reader.analyze(document)
        with self.llm_limiter:
            return self.reader.analyze(document)

    def _publish(self, state: ResearchState, event_type: TaskEventType, payload: ProgressEventPayload) -> None:
        if self.progress_publisher is not None:
            self.progress_publisher.publish(state["run_id"], event_type, payload)

    def _publish_diagnostic(
        self,
        state: ResearchState,
        event_type: TaskEventType,
        payload: dict[str, object],
        *,
        duration_ms: float | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        publisher = self.progress_publisher
        publish = getattr(publisher, "publish_diagnostic", None)
        if publish is not None:
            try:
                publish(
                    state["run_id"],
                    event_type,
                    payload,
                    duration_ms=duration_ms,
                    dedupe_key=dedupe_key,
                )
            except Exception:
                # Diagnostics are strictly best-effort and cannot change the
                # Reader result or exception semantics.
                return
