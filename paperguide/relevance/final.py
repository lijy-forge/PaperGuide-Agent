"""Evidence-aware final relevance and survey sufficiency policies."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from paperguide.analysis import PaperAnalysisResult
from paperguide.domain import PaperCandidate
from paperguide.verification import VerificationStatus, VerifiedPaperAnalysisResult

from .gate import PreliminaryRelevanceClassification
from .models import ResearchIntent


class FinalRelevanceClassification(str, Enum):
    """Full-text/evidence-aware relevance classification."""

    CORE = "core"
    ADJACENT = "adjacent"
    REJECTED = "rejected"


class AssessmentStatus(str, Enum):
    """Whether a paper was assessable after processing."""

    ASSESSED = "assessed"
    UNASSESSABLE = "unassessable"


class ReportMode(str, Enum):
    """Safe report mode derived from evidence coverage."""

    FULL_SURVEY = "full_survey"
    EVIDENCE_LIMITED_REVIEW = "evidence_limited_review"


class FinalRelevanceAssessment(BaseModel):
    """Explainable final relevance result without inventing evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    paper_id: UUID
    preliminary_classification: PreliminaryRelevanceClassification | None = None
    final_classification: FinalRelevanceClassification
    assessment_status: AssessmentStatus = AssessmentStatus.ASSESSED
    fulltext_concept_coverage: float = Field(ge=0.0, le=1.0)
    relation_evidence_strength: float = Field(ge=0.0, le=1.0)
    research_focus_match: float = Field(ge=0.0, le=1.0)
    verified_evidence_coverage: float = Field(ge=0.0, le=1.0)
    evidence_quality: float = Field(ge=0.0, le=1.0)
    conflict_penalty: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=1.0)
    supporting_evidence_keys: list[str] = Field(default_factory=list)
    contradictory_evidence_keys: list[str] = Field(default_factory=list)
    matched_concepts: list[str] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)
    matched_relations: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    selected_for_report: bool = False


class EvidenceSufficiencyAssessment(BaseModel):
    """Corpus-level evidence sufficiency decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    core_paper_count: int = Field(ge=0)
    selected_core_paper_count: int = Field(ge=0)
    verified_evidence_count: int = Field(ge=0)
    relation_evidence_count: int = Field(ge=0)
    evidence_coverage_score: float = Field(ge=0.0, le=1.0)
    metadata_completeness_score: float = Field(ge=0.0, le=1.0)
    cross_paper_coverage: float = Field(ge=0.0, le=1.0)
    conflict_ratio: float = Field(ge=0.0, le=1.0)
    missing_areas: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    recommended_report_mode: ReportMode


class FinalRelevanceAudit(BaseModel):
    """Run-level audit for final relevance and sufficiency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    papers_sent_to_reader: int = Field(ge=0)
    papers_successfully_read: int = Field(ge=0)
    papers_unassessable: int = Field(ge=0)
    final_core_count: int = Field(ge=0)
    final_adjacent_count: int = Field(ge=0)
    final_rejected_count: int = Field(ge=0)
    selected_core_count: int = Field(ge=0)
    core_not_selected_count: int = Field(ge=0)
    verified_evidence_count: int = Field(ge=0)
    recommended_report_mode: ReportMode


class FinalRelevancePolicy(BaseModel):
    """Centralized thresholds for final relevance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    core_threshold: float = Field(default=0.68, ge=0.0, le=1.0)
    adjacent_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    core_concept_coverage: float = Field(default=0.85, ge=0.0, le=1.0)
    core_relation_strength: float = Field(default=0.60, ge=0.0, le=1.0)
    core_evidence_coverage: float = Field(default=0.60, ge=0.0, le=1.0)
    full_survey_min_core_papers: int = Field(default=2, ge=1, le=50)
    full_survey_evidence_coverage: float = Field(default=0.65, ge=0.0, le=1.0)
    full_survey_cross_paper_coverage: float = Field(default=0.50, ge=0.0, le=1.0)


class FinalCoreSelectionPolicy:
    """Select top eligible CORE papers without promoting adjacent papers."""

    def select(self, assessments: Iterable[FinalRelevanceAssessment], papers: dict[UUID, PaperCandidate], max_core_papers: int) -> tuple[list[UUID], int]:
        eligible = [item for item in assessments if item.assessment_status is AssessmentStatus.ASSESSED and item.final_classification is FinalRelevanceClassification.CORE]
        eligible.sort(key=lambda item: (-item.overall_score, -item.relation_evidence_strength, -item.verified_evidence_coverage, item.paper_id.hex))
        selected = [item.paper_id for item in eligible[:max_core_papers] if item.paper_id in papers]
        return selected, max(0, len(eligible) - len(selected))


class EvidenceAwareFinalRelevanceService:
    """Evaluate existing Reader and Verified Evidence outputs deterministically."""

    _WORD_RE = re.compile(r"[\w]+", re.UNICODE)
    _STOP = {"a", "an", "and", "or", "the", "of", "to", "for", "with", "in", "on", "between", "using"}

    def __init__(self, policy: FinalRelevancePolicy | None = None):
        self.policy = policy or FinalRelevancePolicy()

    def assess(self, paper: PaperCandidate, analysis: PaperAnalysisResult | None, verified: VerifiedPaperAnalysisResult | None, intent: ResearchIntent, preliminary: PreliminaryRelevanceClassification | None = None) -> FinalRelevanceAssessment:
        if analysis is None or verified is None:
            return FinalRelevanceAssessment(paper_id=paper.id, preliminary_classification=preliminary, final_classification=FinalRelevanceClassification.ADJACENT, assessment_status=AssessmentStatus.UNASSESSABLE, fulltext_concept_coverage=0, relation_evidence_strength=0, research_focus_match=0, verified_evidence_coverage=0, evidence_quality=0, conflict_penalty=0, overall_score=0, reasons=["processing_failure_unassessable"])
        verified_items = [item for item in verified.verification.verified_evidence if item.status in {VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_SUPPORTED}]
        text = self._normalize(" ".join([paper.title, paper.abstract or "", analysis.research_problem, analysis.method_summary.problem, analysis.method_summary.summary, *analysis.contributions, *analysis.experiment_summary.findings, *(item.claim for item in verified_items), *(item.evidence.quote for item in verified_items)]))
        concepts = [self._normalize(value) for value in intent.required_concepts]
        matched = [original for original, value in zip(intent.required_concepts, concepts) if value in text]
        missing = [original for original, value in zip(intent.required_concepts, concepts) if value not in text]
        concept_coverage = len(matched) / len(concepts) if concepts else 0
        relations = [self._normalize(value) for value in intent.relation_requirements]
        matched_relations = [original for original, relation in zip(intent.relation_requirements, relations) if self._relation_in_evidence(relation, concepts, verified_items)]
        relation_strength = len(matched_relations) / len(relations) if relations else 1.0
        focus_text = self._normalize(" ".join([paper.title, paper.abstract or "", analysis.research_problem, analysis.method_summary.problem, analysis.method_summary.summary, *analysis.contributions]))
        focus_match = (sum(value in focus_text for value in concepts) / len(concepts)) if concepts else 0.0
        evidence_coverage = min(1.0, len(verified_items) / max(1, len(analysis.evidence)))
        evidence_quality = self._evidence_quality(verified_items)
        conflict_penalty = min(1.0, len(verified.verification.conflicts) / max(1, len(verified.verification.verified_evidence)))
        score = max(0.0, min(1.0, 0.26 * concept_coverage + 0.24 * relation_strength + 0.20 * focus_match + 0.18 * evidence_coverage + 0.12 * evidence_quality - 0.10 * conflict_penalty))
        core = concept_coverage >= self.policy.core_concept_coverage and (not relations or relation_strength >= self.policy.core_relation_strength) and focus_match >= self.policy.core_concept_coverage and evidence_coverage >= self.policy.core_evidence_coverage and score >= self.policy.core_threshold
        classification = FinalRelevanceClassification.CORE if core else (FinalRelevanceClassification.ADJACENT if score >= self.policy.adjacent_threshold else FinalRelevanceClassification.REJECTED)
        if not verified_items and analysis.evidence: classification = FinalRelevanceClassification.ADJACENT
        reasons = []
        if missing: reasons.append("missing_fulltext_concepts")
        if relations and not matched_relations: reasons.append("insufficient_relation_evidence")
        if not verified_items: reasons.append("low_verified_evidence_coverage")
        if verified.verification.conflicts: reasons.append("evidence_conflict_uncertainty")
        if not reasons: reasons.append("verified_fulltext_support")
        supporting = [str(item.evidence.id) for item in verified_items]
        contradictory = [str(item.evidence.id) for item in verified.verification.verified_evidence if item.status is VerificationStatus.CONFLICTED]
        return FinalRelevanceAssessment(paper_id=paper.id, preliminary_classification=preliminary, final_classification=classification, fulltext_concept_coverage=concept_coverage, relation_evidence_strength=relation_strength, research_focus_match=focus_match, verified_evidence_coverage=evidence_coverage, evidence_quality=evidence_quality, conflict_penalty=conflict_penalty, overall_score=score, supporting_evidence_keys=supporting, contradictory_evidence_keys=contradictory, matched_concepts=matched, missing_concepts=missing, matched_relations=matched_relations, reasons=reasons)

    def assess_sufficiency(self, assessments: Iterable[FinalRelevanceAssessment], verified_results: Iterable[VerifiedPaperAnalysisResult], intent: ResearchIntent, *, selected_core_count: int | None = None) -> EvidenceSufficiencyAssessment:
        items = list(assessments)
        verified = list(verified_results)
        cores = [item for item in items if item.final_classification is FinalRelevanceClassification.CORE and item.assessment_status is AssessmentStatus.ASSESSED]
        selected = selected_core_count if selected_core_count is not None else len(cores)
        evidence = [item for result in verified for item in result.verification.verified_evidence if item.status in {VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_SUPPORTED}]
        relation_count = sum(bool(item.matched_relations) for item in cores)
        coverage = sum(item.verified_evidence_coverage for item in cores) / len(cores) if cores else 0.0
        metadata_score = sum(item.research_focus_match for item in cores) / len(cores) if cores else 0.0
        paper_ids = {item.evidence.paper_id for item in evidence}
        cross = min(1.0, len(paper_ids) / max(1, len(cores)))
        conflicts = sum(len(result.verification.conflicts) for result in verified)
        conflict_ratio = min(1.0, conflicts / max(1, len(evidence)))
        missing: list[str] = []
        if len(cores) < self.policy.full_survey_min_core_papers: missing.append("insufficient_core_papers")
        if relation_count < len(cores) and intent.relation_requirements: missing.append("insufficient_relation_evidence")
        if coverage < self.policy.full_survey_evidence_coverage: missing.append("low_verified_evidence_coverage")
        if cross < self.policy.full_survey_cross_paper_coverage: missing.append("insufficient_cross_paper_support")
        mode = ReportMode.FULL_SURVEY if not missing else ReportMode.EVIDENCE_LIMITED_REVIEW
        return EvidenceSufficiencyAssessment(core_paper_count=len(cores), selected_core_paper_count=selected, verified_evidence_count=len(evidence), relation_evidence_count=relation_count, evidence_coverage_score=coverage, metadata_completeness_score=metadata_score, cross_paper_coverage=cross, conflict_ratio=conflict_ratio, missing_areas=missing, reasons=list(missing) or ["sufficient_verified_cross_paper_evidence"], recommended_report_mode=mode)

    @classmethod
    def _normalize(cls, value: str) -> str:
        value = unicodedata.normalize("NFKC", value).casefold().replace("-", " ")
        return " ".join(cls._WORD_RE.findall(value))

    @classmethod
    def _relation_in_evidence(cls, relation: str, concepts: list[str], items: list) -> bool:
        relation_tokens = [token for token in cls._WORD_RE.findall(relation) if token not in cls._STOP and token not in {part for concept in concepts for part in concept.split()}]
        for item in items:
            text = cls._normalize(f"{item.claim} {item.evidence.quote}")
            if relation in text or (relation_tokens and all(token in text for token in relation_tokens) and all(concept in text for concept in concepts)):
                return True
        return False

    @staticmethod
    def _evidence_quality(items: list) -> float:
        if not items: return 0.0
        values = []
        for item in items:
            locator = item.evidence.locator
            locator_score = sum(value is not None for value in [locator.section_title, locator.page_start, locator.paragraph_index, locator.char_start]) / 4.0
            values.append(0.7 * item.entailment_score + 0.3 * locator_score)
        return sum(values) / len(values)
