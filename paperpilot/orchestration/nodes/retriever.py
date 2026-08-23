"""Node adapter over the existing PaperSearchPipeline."""

from paperpilot.pipeline import PaperSearchPipeline
from paperpilot.domain import Author, FullTextStatus, PaperCandidate
from paperpilot.services import MetadataNormalizer
from paperpilot.relevance import MultiQueryRetrievalService, RetrievalPlanService
from paperpilot.orchestration.enums import NextAction, ResearchStep
from paperpilot.orchestration.state import ResearchState
from paperpilot.progress.models import ProgressEventPayload, ProgressStage
from paperpilot.progress.publisher import ProgressPublisherProtocol
from paperpilot.progress.events import TaskEventType

from .base import BaseNode


class RetrieverNode(BaseNode):
    """Run the injected search pipeline and translate its result into state."""

    name = "retriever"
    error_step = ResearchStep.RETRIEVAL
    error_next_action = NextAction.EVALUATE_QUALITY
    error_recoverable = True

    def __init__(self, pipeline: PaperSearchPipeline, plan_service: RetrievalPlanService | None = None, multi_query_service: MultiQueryRetrievalService | None = None, progress_publisher: ProgressPublisherProtocol | None = None):
        self.pipeline = pipeline
        self.plan_service = plan_service
        self.multi_query_service = multi_query_service
        self.progress_publisher = progress_publisher

    def _execute(self, state: ResearchState) -> ResearchState:
        self._publish(state, TaskEventType.RETRIEVAL_STARTED, ProgressEventPayload(stage=ProgressStage.RETRIEVAL))
        self._publish(state, TaskEventType.METADATA_FILTERING_STARTED, ProgressEventPayload(stage=ProgressStage.METADATA_FILTERING))
        if self.multi_query_service is not None:
            plan = state.get("retrieval_plan")
            if plan is None:
                if self.plan_service is None:
                    raise ValueError("retrieval plan is required")
                plan = self.plan_service.build(state["question"], max_core_papers=state["research_config"].max_papers)
                state["retrieval_plan"] = plan
            pool, diagnostic = self.multi_query_service.search_with_diagnostics(
                plan, state["research_config"]
            )
            self._publish_diagnostics(state, diagnostic)
            from paperpilot.pipeline import SearchResult
            result = SearchResult(papers=list(pool.papers), source_results=pool.source_results, source_errors=pool.source_errors, warnings=pool.warnings, total_found=pool.audit.raw_candidate_count, total_after_dedup=pool.audit.deduplicated_candidate_count)
            state["retrieval_audit"] = pool.audit
            state["candidate_relevance"] = pool.records
        else:
            result = self.pipeline.search(state["research_config"])
        result = self._merge_manual_sources(
            result, state["research_config"].manual_sources
        )
        state["papers"] = list(result.papers)
        state["search_result"] = result
        state["warnings"] = self._stable_unique(
            [*state.get("warnings", []), *result.warnings]
        )
        # A degraded source is auditable through SearchResult/source warnings.
        # It becomes a workflow error only if no other source produced usable
        # candidates; otherwise arXiv (or another healthy source) can continue.
        if not result.papers:
            for source, message in result.source_errors.items():
                state = self.add_error(
                    state,
                    stage=ResearchStep.RETRIEVAL,
                    recoverable=True,
                    error_type=f"{source}RetrieverError",
                    message=message,
                )
        state["current_step"] = ResearchStep.RETRIEVAL
        state["next_action"] = NextAction.INGEST
        audit = state.get("retrieval_audit")
        self._publish(state, TaskEventType.RETRIEVAL_COMPLETED, ProgressEventPayload(stage=ProgressStage.RETRIEVAL, completed=(audit.executed_query_count if audit else 1), total=(audit.planned_query_count if audit else 1), message=(f"{audit.raw_candidate_count} candidates" if audit else None)))
        if audit is not None:
            self._publish(state, TaskEventType.METADATA_FILTERING_COMPLETED, ProgressEventPayload(stage=ProgressStage.METADATA_FILTERING, completed=audit.deduplicated_candidate_count, total=audit.deduplicated_candidate_count, message=f"{audit.selected_for_ingestion_count} selected"))
        return state

    @staticmethod
    def _merge_manual_sources(result, manual_sources):
        if not manual_sources:
            return result
        papers = list(result.papers)
        title_index = {paper.normalized_title: index for index, paper in enumerate(papers)}
        for manual in manual_sources:
            normalized_title = MetadataNormalizer.normalize_title(manual.title)
            authors = [
                Author(full_name=name, affiliations=[]) for name in manual.authors
            ]
            upload_url = f"paperpilot-upload://{manual.upload_id}"
            existing_index = title_index.get(normalized_title)
            if existing_index is not None:
                existing = papers[existing_index]
                papers[existing_index] = existing.model_copy(
                    update={
                        "abstract": existing.abstract or manual.abstract,
                        "authors": existing.authors or authors,
                        "publication_year": existing.publication_year or manual.publication_year,
                        "doi": existing.doi or manual.doi,
                        "sources": list(dict.fromkeys([*existing.sources, manual.source])),
                        "landing_page_url": manual.source_url,
                        "pdf_url": upload_url,
                        "full_text_status": FullTextStatus.AVAILABLE,
                        "selection_reason": "人工补充的全文 PDF，参与统一证据分析。",
                    }
                )
                continue
            title_index[normalized_title] = len(papers)
            papers.append(
                PaperCandidate(
                    title=manual.title,
                    normalized_title=normalized_title,
                    abstract=manual.abstract,
                    authors=authors,
                    publication_year=manual.publication_year,
                    doi=manual.doi,
                    sources=[manual.source],
                    landing_page_url=manual.source_url,
                    pdf_url=upload_url,
                    full_text_status=FullTextStatus.AVAILABLE,
                    selection_reason="人工补充的全文 PDF，参与统一证据分析。",
                )
            )
        return result.model_copy(
            update={
                "papers": papers,
                "source_results": {
                    **result.source_results,
                    "manual": len(manual_sources),
                },
                "warnings": [
                    *result.warnings,
                    f"已纳入 {len(manual_sources)} 篇人工补充全文。",
                ],
                "total_found": result.total_found + len(manual_sources),
                "total_after_dedup": len(papers),
            }
        )

    def _publish(self, state: ResearchState, event_type: TaskEventType, payload: ProgressEventPayload) -> None:
        if self.progress_publisher is not None:
            self.progress_publisher.publish(state["run_id"], event_type, payload)

    def _publish_diagnostic(
        self,
        state: ResearchState,
        event_type: TaskEventType,
        payload: dict[str, object],
        dedupe_key: str,
    ) -> None:
        publisher = self.progress_publisher
        publish = getattr(publisher, "publish_diagnostic", None)
        if publish is None:
            return
        try:
            publish(
                state["run_id"],
                event_type,
                payload,
                dedupe_key=dedupe_key,
            )
        except Exception:
            # Private audit events must never change retrieval behavior.
            return

    def _publish_diagnostics(self, state: ResearchState, diagnostic) -> None:
        if diagnostic is None:
            return
        for query in diagnostic.queries:
            self._publish_diagnostic(
                state,
                TaskEventType.QUERY_PLAN_AUDIT,
                {
                    "query_index": query.query_index,
                    "language": query.language,
                    "normalized_query_hash": query.normalized_query_hash,
                    "safe_query_preview": query.safe_query_preview,
                    "char_count": query.char_count,
                    "exact_duplicate": query.exact_duplicate,
                    "normalized_duplicate": query.normalized_duplicate,
                    "raw_result_count": query.raw_result_count,
                },
                f"audit:query:{query.query_index}",
            )
            for result_index, (identity_type, identity_hash, title_preview) in enumerate(
                zip(
                    query.result_identity_types,
                    query.result_identities,
                    query.result_title_previews,
                ),
                1,
            ):
                self._publish_diagnostic(
                    state,
                    TaskEventType.RETRIEVAL_RESULT_AUDIT,
                    {
                        "query_index": query.query_index,
                        "result_index": result_index,
                        "identity_type": identity_type,
                        "identity_hash": identity_hash,
                        "safe_title_preview": title_preview,
                    },
                    f"audit:query:{query.query_index}:result:{result_index}",
                )
        for overlap in diagnostic.overlaps:
            self._publish_diagnostic(
                state,
                TaskEventType.RETRIEVAL_OVERLAP_AUDIT,
                overlap.model_dump(),
                f"audit:overlap:{overlap.left_query_index}:{overlap.right_query_index}",
            )
        for group in diagnostic.dedup_groups:
            self._publish_diagnostic(
                state,
                TaskEventType.DEDUP_GROUP_AUDIT,
                {
                    "group_index": group.group_index,
                    "group_size": group.group_size,
                    "canonical_identity_type": group.canonical_identity_type,
                    "canonical_identity_hash": group.canonical_identity_hash,
                    "matched_by": ",".join(group.matched_by),
                    "potentially_incorrect": group.potentially_incorrect,
                },
                f"audit:dedup:{group.group_index}",
            )
            for member_index, (identity_hash, title_preview) in enumerate(
                zip(group.member_identity_hashes, group.member_title_previews), 1
            ):
                self._publish_diagnostic(
                    state,
                    TaskEventType.DEDUP_GROUP_MEMBER_AUDIT,
                    {
                        "group_index": group.group_index,
                        "member_index": member_index,
                        "identity_hash": identity_hash,
                        "safe_title_preview": title_preview,
                    },
                    f"audit:dedup:{group.group_index}:member:{member_index}",
                )
        intent = diagnostic.intent
        self._publish_diagnostic(
            state,
            TaskEventType.RESEARCH_INTENT_AUDIT,
            {
                "query_language": intent.query_language,
                "required_concept_count": intent.required_concept_count,
                "related_concept_count": intent.related_concept_count,
                "relation_requirement_count": intent.relation_requirement_count,
                "exclusion_concept_count": intent.exclusion_concept_count,
                "domain_present": intent.domain_present,
                "method_concept_count": intent.method_concept_count,
                "application_concept_count": intent.application_concept_count,
                "zh_term_count": intent.language_counts.get("ZH", 0),
                "en_term_count": intent.language_counts.get("EN", 0),
                "mixed_term_count": intent.language_counts.get("MIXED", 0),
            },
            "audit:intent:summary",
        )
        for term in intent.terms:
            self._publish_diagnostic(
                state,
                TaskEventType.RESEARCH_INTENT_TERM_AUDIT,
                term.model_dump(),
                f"audit:intent:{term.category}:{term.term_index}",
            )
        for candidate in diagnostic.candidates:
            self._publish_diagnostic(
                state,
                TaskEventType.METADATA_CANDIDATE_AUDIT,
                candidate.model_dump(),
                f"audit:metadata:{candidate.candidate_index}",
            )
        self._publish_diagnostic(
            state,
            TaskEventType.METADATA_SUMMARY_AUDIT,
            {
                "planned_query_count": diagnostic.planned_query_count,
                "intent_planner_fallback": diagnostic.intent_planner_fallback,
                "query_expansion_fallback": diagnostic.query_expansion_fallback,
                "exact_unique_query_count": diagnostic.exact_unique_query_count,
                "normalized_unique_query_count": diagnostic.normalized_unique_query_count,
                "duplicate_query_count": diagnostic.duplicate_query_count,
                "unique_identity_count_before_dedup": diagnostic.unique_identity_count_before_dedup,
                "deduplicated_count": diagnostic.deduplicated_count,
                "mean_pairwise_jaccard": diagnostic.mean_pairwise_jaccard,
                "max_pairwise_jaccard": diagnostic.max_pairwise_jaccard,
                "suspicious_dedup_group_count": diagnostic.suspicious_dedup_group_count,
                "score_min": diagnostic.score_min,
                "score_median": diagnostic.score_median,
                "score_max": diagnostic.score_max,
                "closest_score_to_adjacent_threshold": diagnostic.closest_score_to_adjacent_threshold,
                "metadata_determinism": diagnostic.metadata_determinism,
                "score_arithmetic_consistent": diagnostic.score_arithmetic_consistent,
            },
            "audit:metadata:summary",
        )

    @staticmethod
    def _stable_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
