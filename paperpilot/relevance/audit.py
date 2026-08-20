"""Safe, deterministic diagnostics for the retrieval-to-metadata funnel."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from itertools import combinations
from statistics import median

from pydantic import BaseModel, ConfigDict, Field

from paperpilot.domain import PaperCandidate
from paperpilot.services import MetadataNormalizer

from .gate import MetadataRelevanceAssessment, MetadataRelevanceGate
from .models import ResearchIntent, RetrievalPlan

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def normalize_audit_text(value: str) -> str:
    """Normalize text for diagnostic equality without changing business input."""

    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def audit_hash(value: str) -> str:
    """Return a stable SHA256 identifier for non-public diagnostic correlation."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_preview(value: str | None, limit: int = 100) -> str:
    """Return a whitespace-normalized, bounded preview."""

    return " ".join((value or "").split())[:limit]


def classify_text_language(value: str) -> str:
    """Classify text as ZH, EN, or MIXED using literal script presence."""

    has_cjk = bool(_CJK_RE.search(value))
    has_latin = bool(_LATIN_RE.search(value))
    if has_cjk and not has_latin:
        return "ZH"
    if has_latin and not has_cjk:
        return "EN"
    return "MIXED"


def stable_paper_identity(paper: PaperCandidate) -> tuple[str, str]:
    """Hash the strongest public paper identity without exposing its value."""

    candidates = (
        ("arxiv_id", MetadataNormalizer.normalize_arxiv_id(paper.arxiv_id)),
        ("doi", MetadataNormalizer.normalize_doi(paper.doi)),
        ("semantic_scholar_id", _normalized_scalar(paper.semantic_scholar_id)),
        ("openalex_id", _normalized_scalar(paper.openalex_id)),
        ("landing_page_url", MetadataNormalizer.normalize_url(paper.landing_page_url)),
        ("pdf_url", MetadataNormalizer.normalize_url(paper.pdf_url)),
        ("normalized_title", MetadataNormalizer.normalize_title(paper.title)),
    )
    identity_type, value = next(
        ((kind, value) for kind, value in candidates if value),
        ("metadata_fallback", normalize_audit_text(paper.title)),
    )
    return identity_type, audit_hash(f"{identity_type}:{value}")


def _normalized_scalar(value: str | None) -> str | None:
    normalized = (value or "").strip().rstrip("/").casefold()
    return normalized or None


class QueryDiagnostic(BaseModel):
    """One planned query plus its bounded result diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query_index: int = Field(ge=1)
    language: str
    normalized_query_hash: str
    safe_query_preview: str = Field(max_length=120)
    char_count: int = Field(ge=0)
    exact_duplicate: bool
    normalized_duplicate: bool
    raw_result_count: int = Field(ge=0)
    result_identities: list[str] = Field(default_factory=list)
    result_identity_types: list[str] = Field(default_factory=list)
    result_title_previews: list[str] = Field(default_factory=list)


class RetrievalOverlapDiagnostic(BaseModel):
    """Exact identity overlap between two planned-query result sets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    left_query_index: int = Field(ge=1)
    right_query_index: int = Field(ge=1)
    intersection_count: int = Field(ge=0)
    union_count: int = Field(ge=0)
    jaccard: float = Field(ge=0.0, le=1.0)


class DedupGroupDiagnostic(BaseModel):
    """Safe sample of one real deduplication group."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group_index: int = Field(ge=1)
    group_size: int = Field(ge=2)
    canonical_identity_type: str
    canonical_identity_hash: str
    matched_by: list[str]
    member_identity_hashes: list[str]
    member_title_previews: list[str]
    potentially_incorrect: bool


class IntentTermDiagnostic(BaseModel):
    """Hashed intent term retained without LLM reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    term_index: int = Field(ge=1)
    language: str
    term_hash: str
    safe_term_preview: str = Field(max_length=100)


class IntentDiagnostic(BaseModel):
    """Language and cardinality summary of the actual ResearchIntent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query_language: str
    required_concept_count: int = Field(ge=0)
    related_concept_count: int = Field(ge=0)
    relation_requirement_count: int = Field(ge=0)
    exclusion_concept_count: int = Field(ge=0)
    domain_present: bool
    method_concept_count: int | None = None
    application_concept_count: int | None = None
    language_counts: dict[str, int]
    terms: list[IntentTermDiagnostic]


class MetadataCandidateDiagnostic(BaseModel):
    """Safe feature record for one deterministic metadata assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_index: int = Field(ge=1)
    identity_type: str
    identity_hash: str
    title_preview: str = Field(max_length=100)
    year: int | None
    title_present: bool
    abstract_present: bool
    abstract_char_count: int = Field(ge=0)
    metadata_language: str
    metadata_score: float
    classification: str
    selected_for_ingestion: bool
    required_concept_coverage: float
    relation_support: float
    scope_match: float
    time_match: float
    exclusion_penalty: float
    metadata_quality: float
    distance_to_adjacent_threshold: float
    distance_to_core_threshold: float
    matched_zh_term_count: int = Field(ge=0)
    matched_en_term_count: int = Field(ge=0)
    score_arithmetic_consistent: bool


class RetrievalMetadataDiagnostic(BaseModel):
    """Complete private audit snapshot for one deterministic funnel run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    queries: list[QueryDiagnostic]
    overlaps: list[RetrievalOverlapDiagnostic]
    dedup_groups: list[DedupGroupDiagnostic]
    intent: IntentDiagnostic
    candidates: list[MetadataCandidateDiagnostic]
    planned_query_count: int = Field(ge=0)
    intent_planner_fallback: bool
    query_expansion_fallback: bool
    exact_unique_query_count: int = Field(ge=0)
    normalized_unique_query_count: int = Field(ge=0)
    duplicate_query_count: int = Field(ge=0)
    unique_identity_count_before_dedup: int = Field(ge=0)
    deduplicated_count: int = Field(ge=0)
    mean_pairwise_jaccard: float = Field(ge=0.0, le=1.0)
    max_pairwise_jaccard: float = Field(ge=0.0, le=1.0)
    suspicious_dedup_group_count: int = Field(ge=0)
    score_min: float | None
    score_median: float | None
    score_max: float | None
    closest_score_to_adjacent_threshold: float | None
    metadata_determinism: bool | None
    score_arithmetic_consistent: bool


def query_diagnostics(
    plan: RetrievalPlan,
    result_papers: list[list[PaperCandidate]],
) -> tuple[list[QueryDiagnostic], list[RetrievalOverlapDiagnostic]]:
    """Create query duplicate and exact result-overlap diagnostics."""

    exact_seen: set[str] = set()
    normalized_seen: set[str] = set()
    records: list[QueryDiagnostic] = []
    for index, variant in enumerate(plan.query_variants[: plan.budget.max_query_variants], 1):
        exact = variant.query
        normalized = normalize_audit_text(exact)
        papers = result_papers[index - 1] if index <= len(result_papers) else []
        identities = [stable_paper_identity(paper) for paper in papers]
        records.append(
            QueryDiagnostic(
                query_index=index,
                language=classify_text_language(exact),
                normalized_query_hash=audit_hash(normalized),
                safe_query_preview=safe_preview(exact, 120),
                char_count=len(exact),
                exact_duplicate=exact in exact_seen,
                normalized_duplicate=normalized in normalized_seen,
                raw_result_count=len(papers),
                result_identities=[identity_hash for _, identity_hash in identities],
                result_identity_types=[identity_type for identity_type, _ in identities],
                result_title_previews=[safe_preview(paper.title) for paper in papers],
            )
        )
        exact_seen.add(exact)
        normalized_seen.add(normalized)

    overlaps: list[RetrievalOverlapDiagnostic] = []
    for left, right in combinations(records, 2):
        left_set, right_set = set(left.result_identities), set(right.result_identities)
        union = left_set | right_set
        intersection = left_set & right_set
        overlaps.append(
            RetrievalOverlapDiagnostic(
                left_query_index=left.query_index,
                right_query_index=right.query_index,
                intersection_count=len(intersection),
                union_count=len(union),
                jaccard=(len(intersection) / len(union)) if union else 1.0,
            )
        )
    return records, overlaps


def intent_diagnostic(intent: ResearchIntent) -> IntentDiagnostic:
    """Summarize the actual intent fields and term languages."""

    categories = (
        ("required", intent.required_concepts),
        ("related", intent.related_concepts),
        ("relation", intent.relation_requirements),
        ("exclusion", intent.exclusion_concepts),
        ("domain", [intent.domain] if intent.domain else []),
    )
    terms: list[IntentTermDiagnostic] = []
    for category, values in categories:
        for index, term in enumerate(values, 1):
            normalized = normalize_audit_text(term)
            terms.append(
                IntentTermDiagnostic(
                    category=category,
                    term_index=index,
                    language=classify_text_language(term),
                    term_hash=audit_hash(normalized),
                    safe_term_preview=safe_preview(term),
                )
            )
    return IntentDiagnostic(
        query_language=intent.query_language or classify_text_language(intent.research_question),
        required_concept_count=len(intent.required_concepts),
        related_concept_count=len(intent.related_concepts),
        relation_requirement_count=len(intent.relation_requirements),
        exclusion_concept_count=len(intent.exclusion_concepts),
        domain_present=bool(intent.domain),
        method_concept_count=None,
        application_concept_count=None,
        language_counts=dict(Counter(term.language for term in terms)),
        terms=terms,
    )


def candidate_diagnostics(
    papers: list[PaperCandidate],
    assessments: list[MetadataRelevanceAssessment],
    selected_ids: set[object],
    gate: MetadataRelevanceGate,
) -> list[MetadataCandidateDiagnostic]:
    """Build arithmetic-verifiable records from existing score components."""

    records: list[MetadataCandidateDiagnostic] = []
    for index, (paper, assessment) in enumerate(zip(papers, assessments), 1):
        identity_type, identity_hash = stable_paper_identity(paper)
        matched_terms = [
            *assessment.matched_concepts,
            *assessment.matched_relations,
            *assessment.matched_exclusions,
        ]
        matched_languages = Counter(classify_text_language(term) for term in matched_terms)
        recomputed = max(
            0.0,
            min(
                1.0,
                0.32 * assessment.required_concept_coverage
                + 0.24 * assessment.relation_support
                + 0.16 * assessment.scope_match
                + 0.12 * assessment.time_match
                + 0.10 * assessment.metadata_quality
                - 0.16 * assessment.exclusion_penalty,
            ),
        )
        records.append(
            MetadataCandidateDiagnostic(
                candidate_index=index,
                identity_type=identity_type,
                identity_hash=identity_hash,
                title_preview=safe_preview(paper.title),
                year=paper.publication_year,
                title_present=bool(paper.title.strip()),
                abstract_present=bool(paper.abstract and paper.abstract.strip()),
                abstract_char_count=len((paper.abstract or "").strip()),
                metadata_language=classify_text_language(
                    " ".join(filter(None, [paper.title, paper.abstract]))
                ),
                metadata_score=assessment.overall_score,
                classification=assessment.classification.value,
                selected_for_ingestion=paper.id in selected_ids,
                required_concept_coverage=assessment.required_concept_coverage,
                relation_support=assessment.relation_support,
                scope_match=assessment.scope_match,
                time_match=assessment.time_match,
                exclusion_penalty=assessment.exclusion_penalty,
                metadata_quality=assessment.metadata_quality,
                distance_to_adjacent_threshold=(
                    assessment.overall_score - gate.policy.adjacent_threshold
                ),
                distance_to_core_threshold=(
                    assessment.overall_score - gate.policy.core_threshold
                ),
                matched_zh_term_count=matched_languages["ZH"],
                matched_en_term_count=matched_languages["EN"],
                score_arithmetic_consistent=math.isclose(
                    recomputed, assessment.overall_score, rel_tol=0.0, abs_tol=1e-12
                ),
            )
        )
    return records


def diagnostic_summary(
    *,
    plan: RetrievalPlan,
    query_records: list[QueryDiagnostic],
    overlaps: list[RetrievalOverlapDiagnostic],
    dedup_groups: list[DedupGroupDiagnostic],
    deduplicated_count: int,
    candidates: list[MetadataCandidateDiagnostic],
    deterministic: bool,
) -> RetrievalMetadataDiagnostic:
    """Assemble aggregate metrics without changing the candidate pipeline."""

    scores = sorted(candidate.metadata_score for candidate in candidates)
    jaccards = [item.jaccard for item in overlaps]
    identities = {
        identity
        for query in query_records
        for identity in query.result_identities
    }
    adjacent = MetadataRelevanceGate().policy.adjacent_threshold
    return RetrievalMetadataDiagnostic(
        queries=query_records,
        overlaps=overlaps,
        dedup_groups=dedup_groups,
        intent=intent_diagnostic(plan.intent),
        candidates=candidates,
        planned_query_count=plan.planned_query_count,
        intent_planner_fallback="INTENT_PLANNER_FALLBACK" in plan.warnings,
        query_expansion_fallback="QUERY_EXPANSION_FALLBACK" in plan.warnings,
        exact_unique_query_count=len({query.query for query in plan.query_variants[: plan.budget.max_query_variants]}),
        normalized_unique_query_count=len({normalize_audit_text(query.query) for query in plan.query_variants[: plan.budget.max_query_variants]}),
        duplicate_query_count=sum(query.normalized_duplicate for query in query_records),
        unique_identity_count_before_dedup=len(identities),
        deduplicated_count=deduplicated_count,
        mean_pairwise_jaccard=(sum(jaccards) / len(jaccards)) if jaccards else 0.0,
        max_pairwise_jaccard=max(jaccards, default=0.0),
        suspicious_dedup_group_count=sum(group.potentially_incorrect for group in dedup_groups),
        score_min=min(scores) if scores else None,
        score_median=median(scores) if scores else None,
        score_max=max(scores) if scores else None,
        closest_score_to_adjacent_threshold=(
            min(scores, key=lambda score: abs(score - adjacent)) if scores else None
        ),
        metadata_determinism=deterministic if candidates else None,
        score_arithmetic_consistent=all(
            candidate.score_arithmetic_consistent for candidate in candidates
        ),
    )
