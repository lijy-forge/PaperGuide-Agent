"""Multi-query retrieval, candidate pooling, selection and audit contracts."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from paperpilot.domain import PaperCandidate, ResearchConfig
from paperpilot.pipeline import PaperSearchPipeline
from paperpilot.services import PaperDeduplicator

from .gate import MetadataRelevanceAssessment, MetadataRelevanceGate, PreliminaryRelevanceClassification
from .models import RetrievalPlan
from .audit import (
    DedupGroupDiagnostic,
    RetrievalMetadataDiagnostic,
    candidate_diagnostics,
    diagnostic_summary,
    query_diagnostics,
    safe_preview,
    stable_paper_identity,
)


class RetrievalAudit(BaseModel):
    """Counts and rejection reasons produced by one bounded retrieval run."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    planned_query_count: int = Field(ge=0)
    executed_query_count: int = Field(ge=0)
    failed_query_count: int = Field(ge=0)
    raw_candidate_count: int = Field(ge=0)
    deduplicated_candidate_count: int = Field(ge=0)
    candidate_budget_count: int = Field(ge=0)
    preliminary_core_count: int = Field(ge=0)
    possible_adjacent_count: int = Field(ge=0)
    metadata_rejected_count: int = Field(ge=0)
    selected_for_ingestion_count: int = Field(ge=0)
    rejection_reason_counts: dict[str, int] = Field(default_factory=dict)


class CandidateRelevanceRecord(BaseModel):
    """Per-paper relevance record retained for later audit/reporting."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    paper_id: UUID
    classification: PreliminaryRelevanceClassification
    overall_score: float = Field(ge=0.0, le=1.0)
    matched_concepts: list[str] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)
    matched_relations: list[str] = Field(default_factory=list)
    query_provenance: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class CandidatePoolResult(BaseModel):
    """Selected papers plus diagnostics from multi-query retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    papers: list[PaperCandidate]
    records: list[CandidateRelevanceRecord]
    provenance: dict[str, list[str]]
    source_results: dict[str, int]
    source_errors: dict[str, str]
    warnings: list[str]
    audit: RetrievalAudit


class CandidateSelectionPolicy:
    """Prefer preliminary core candidates, then adjacent candidates, deterministically."""

    def select(self, papers: list[PaperCandidate], assessments: list[MetadataRelevanceAssessment], provenance: dict[str, list[str]], *, max_documents: int) -> tuple[list[PaperCandidate], list[CandidateRelevanceRecord]]:
        by_id = {assessment.paper_id: assessment for assessment in assessments}
        ranked = sorted(papers, key=lambda paper: self._key(paper, by_id[paper.id]))
        selected: list[PaperCandidate] = []
        records: list[CandidateRelevanceRecord] = []
        for paper in ranked:
            assessment = by_id[paper.id]
            query_ids = list(provenance.get(str(paper.id), []))
            records.append(CandidateRelevanceRecord(paper_id=paper.id, classification=assessment.classification, overall_score=assessment.overall_score, matched_concepts=assessment.matched_concepts, missing_concepts=assessment.missing_concepts, matched_relations=assessment.matched_relations, query_provenance=query_ids, reasons=assessment.reasons))
            if assessment.classification is not PreliminaryRelevanceClassification.REJECTED and len(selected) < max_documents:
                selected.append(paper.model_copy(deep=True))
        return selected, records

    @staticmethod
    def _key(paper: PaperCandidate, assessment: MetadataRelevanceAssessment) -> tuple[int, float, int, str]:
        priority = {PreliminaryRelevanceClassification.PRELIMINARY_CORE: 0, PreliminaryRelevanceClassification.POSSIBLE_ADJACENT: 1, PreliminaryRelevanceClassification.REJECTED: 2}[assessment.classification]
        return priority, -assessment.overall_score, -(paper.publication_year or 0), paper.normalized_title.casefold()


class MultiQueryRetrievalService:
    """Execute a bounded retrieval plan and apply deduplication and metadata gating."""

    def __init__(self, pipeline: PaperSearchPipeline, deduplicator: PaperDeduplicator | None = None, gate: MetadataRelevanceGate | None = None, selector: CandidateSelectionPolicy | None = None):
        self.pipeline = pipeline
        self.deduplicator = deduplicator or PaperDeduplicator()
        self.gate = gate or MetadataRelevanceGate()
        self.selector = selector or CandidateSelectionPolicy()

    def search(self, plan: RetrievalPlan, config: ResearchConfig) -> CandidatePoolResult:
        result, _ = self.search_with_diagnostics(plan, config)
        return result

    def search_with_diagnostics(
        self, plan: RetrievalPlan, config: ResearchConfig
    ) -> tuple[CandidatePoolResult, RetrievalMetadataDiagnostic | None]:
        """Return the unchanged business result plus best-effort private audit data."""

        raw: list[PaperCandidate] = []
        per_query_papers: list[list[PaperCandidate]] = []
        provenance: dict[str, list[str]] = {}
        source_results: dict[str, int] = {}
        source_errors: dict[str, str] = {}
        active_sources = list(config.sources)
        warnings = list(plan.warnings)
        executed = failed = 0
        for index, variant in enumerate(plan.query_variants[: plan.budget.max_query_variants]):
            if not active_sources:
                warnings.append("ALL_RETRIEVER_SOURCES_UNAVAILABLE")
                break
            executed += 1
            query_id = f"query_{index + 1}"
            query_config = config.model_copy(
                update={
                    "question": variant.query,
                    "max_papers": plan.budget.max_candidates_per_query,
                    "sources": active_sources,
                }
            )
            try:
                result = self.pipeline.search(query_config)
                for source, count in result.source_results.items(): source_results[source] = source_results.get(source, 0) + count
                bounded_papers = result.papers[: plan.budget.max_candidates_per_query]
                per_query_papers.append(list(bounded_papers))
                raw.extend(bounded_papers)
                for paper in bounded_papers: provenance.setdefault(str(paper.id), []).append(query_id)
                failed_sources = set(result.source_errors)
                for source in failed_sources:
                    source_errors[source] = "RETRIEVER_SOURCE_FAILED"
                    warnings.append(f"RETRIEVER_SOURCE_FAILED:{source}")
                # A source-level failure (notably a rate-limit response) should
                # not be retried for every planned query. Continue with healthy
                # sources so one provider cannot exhaust the full task budget.
                if failed_sources:
                    active_sources = [
                        source
                        for source in active_sources
                        if source.value not in failed_sources
                    ]
                # Existing pipeline warnings may contain provider text. Keep only
                # stable diagnostic codes at this boundary.
                warnings.extend(
                    warning
                    for warning in result.warnings
                    if warning.startswith(("Retriever ", "DEDUP", "RETRIEVER_"))
                    and "failed:" not in warning.casefold()
                )
            except Exception:
                failed += 1
                per_query_papers.append([])
                warnings.append("RETRIEVAL_QUERY_FAILED")
        dedup = self.deduplicator.deduplicate(raw)
        merged_provenance = self._merge_provenance(dedup, provenance)
        if len(dedup.papers) > plan.budget.max_candidates_after_dedup:
            dedup_papers = self._trim(dedup.papers, plan.budget.max_candidates_after_dedup)
            dedup_provenance = {str(paper.id): merged_provenance.get(str(paper.id), []) for paper in dedup_papers}
        else:
            dedup_papers, dedup_provenance = dedup.papers, merged_provenance
        assessments = self.gate.assess_many(dedup_papers, plan.intent)
        selected, records = self.selector.select(
            dedup_papers,
            assessments,
            dedup_provenance,
            max_documents=min(
                plan.budget.max_documents_to_ingest,
                plan.budget.max_papers_to_read,
            ),
        )
        counts = Counter(item.classification for item in assessments)
        reasons = Counter(reason for item in assessments if item.classification is PreliminaryRelevanceClassification.REJECTED for reason in item.reasons)
        audit = RetrievalAudit(planned_query_count=plan.planned_query_count, executed_query_count=executed, failed_query_count=failed, raw_candidate_count=len(raw), deduplicated_candidate_count=len(dedup.papers), candidate_budget_count=plan.max_candidate_budget, preliminary_core_count=counts[PreliminaryRelevanceClassification.PRELIMINARY_CORE], possible_adjacent_count=counts[PreliminaryRelevanceClassification.POSSIBLE_ADJACENT], metadata_rejected_count=counts[PreliminaryRelevanceClassification.REJECTED], selected_for_ingestion_count=len(selected), rejection_reason_counts=dict(reasons))
        if failed and failed == executed and not raw:
            warnings.append("ALL_RETRIEVAL_QUERIES_FAILED")
        result = CandidatePoolResult(papers=selected, records=records, provenance=dedup_provenance, source_results=source_results, source_errors=source_errors, warnings=list(dict.fromkeys(warnings + dedup.warnings)), audit=audit)
        diagnostic: RetrievalMetadataDiagnostic | None = None
        try:
            query_records, overlaps = query_diagnostics(plan, per_query_papers)
            raw_by_id = {paper.id: paper for paper in raw}
            group_records: list[DedupGroupDiagnostic] = []
            for group_index, group in enumerate(dedup.merged_groups[:5], 1):
                member_ids = [group.canonical_paper_id, *group.merged_paper_ids]
                members = [raw_by_id[paper_id] for paper_id in member_ids if paper_id in raw_by_id]
                canonical = raw_by_id.get(group.canonical_paper_id)
                if canonical is None or len(members) < 2:
                    continue
                canonical_type, canonical_hash = stable_paper_identity(canonical)
                member_identities = [stable_paper_identity(paper) for paper in members]
                public_hashes = {identity_hash for _, identity_hash in member_identities}
                strong_match = bool(set(group.matched_by) & {"doi", "arxiv_id", "semantic_scholar_id", "openalex_id"})
                group_records.append(
                    DedupGroupDiagnostic(
                        group_index=group_index,
                        group_size=len(members),
                        canonical_identity_type=canonical_type,
                        canonical_identity_hash=canonical_hash,
                        matched_by=group.matched_by,
                        member_identity_hashes=[identity_hash for _, identity_hash in member_identities],
                        member_title_previews=[safe_preview(paper.title) for paper in members],
                        potentially_incorrect=len(public_hashes) > 1 and not strong_match,
                    )
                )
            selected_ids = {paper.id for paper in selected}
            candidate_records = candidate_diagnostics(
                dedup_papers, assessments, selected_ids, self.gate
            )
            replay_one = self.gate.assess_many(dedup_papers, plan.intent)
            replay_two = self.gate.assess_many(dedup_papers, plan.intent)
            deterministic = (
                [item.model_dump(mode="json") for item in assessments]
                == [item.model_dump(mode="json") for item in replay_one]
                == [item.model_dump(mode="json") for item in replay_two]
            )
            diagnostic = diagnostic_summary(
                plan=plan,
                query_records=query_records,
                overlaps=overlaps,
                dedup_groups=group_records,
                deduplicated_count=len(dedup.papers),
                candidates=candidate_records,
                deterministic=deterministic,
            )
        except Exception:
            # Auditability is best-effort and must never alter retrieval output.
            diagnostic = None
        return result, diagnostic

    @staticmethod
    def _trim(papers: list[PaperCandidate], limit: int) -> list[PaperCandidate]:
        return sorted(papers, key=lambda paper: (-(paper.relevance_score or 0.0), -(paper.publication_year or 0), paper.normalized_title.casefold()))[:limit]

    @staticmethod
    def _merge_provenance(dedup, provenance: dict[str, list[str]]) -> dict[str, list[str]]:
        merged = {str(paper.id): list(provenance.get(str(paper.id), [])) for paper in dedup.papers}
        for group in dedup.merged_groups:
            values: list[str] = []
            for paper_id in [group.canonical_paper_id, *group.merged_paper_ids]: values.extend(provenance.get(str(paper_id), []))
            merged[str(group.canonical_paper_id)] = list(dict.fromkeys(values))
        return merged
