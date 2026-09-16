"""Deterministic metadata relevance assessment and classification."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from paperguide.domain import PaperCandidate

from .models import ResearchIntent


class PreliminaryRelevanceClassification(str, Enum):
    """Metadata-only classification; it is deliberately distinct from final relevance."""

    PRELIMINARY_CORE = "preliminary_core"
    POSSIBLE_ADJACENT = "possible_adjacent"
    REJECTED = "rejected"


class MetadataRelevanceAssessment(BaseModel):
    """Explainable, metadata-only relevance features for one candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    paper_id: UUID
    classification: PreliminaryRelevanceClassification = PreliminaryRelevanceClassification.POSSIBLE_ADJACENT
    required_concept_coverage: float = Field(ge=0.0, le=1.0)
    relation_support: float = Field(ge=0.0, le=1.0)
    scope_match: float = Field(ge=0.0, le=1.0)
    time_match: float = Field(ge=0.0, le=1.0)
    exclusion_penalty: float = Field(ge=0.0, le=1.0)
    metadata_quality: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=1.0)
    matched_concepts: list[str] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)
    matched_relations: list[str] = Field(default_factory=list)
    matched_exclusions: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class MetadataRelevancePolicy(BaseModel):
    """Centralized deterministic thresholds and score weights."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    core_threshold: float = Field(default=0.68, ge=0.0, le=1.0)
    adjacent_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    core_concept_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    core_relation_support: float = Field(default=1.0, ge=0.0, le=1.0)


class MetadataRelevanceGate:
    """Classify candidates using only normalized title/abstract metadata."""

    _WORD_RE = re.compile(r"[\w]+", re.UNICODE)
    _STOP = {"a", "an", "and", "or", "the", "of", "to", "for", "with", "in", "on", "between", "using"}

    def __init__(self, policy: MetadataRelevancePolicy | None = None):
        self.policy = policy or MetadataRelevancePolicy()

    def assess(self, paper: PaperCandidate, intent: ResearchIntent) -> MetadataRelevanceAssessment:
        text = self._normalize(" ".join(filter(None, [paper.title, paper.abstract])))
        title = self._normalize(paper.title)
        required = [self._normalize(term) for term in intent.required_concepts]
        matched = [original for original, normalized in zip(intent.required_concepts, required) if self._contains(text, normalized)]
        missing = [original for original, normalized in zip(intent.required_concepts, required) if not self._contains(text, normalized)]
        coverage = len(matched) / len(required) if required else 0.0

        relations = [self._normalize(term) for term in intent.relation_requirements]
        matched_relations = [original for original, normalized in zip(intent.relation_requirements, relations) if self._relation_supported(text, normalized, required)]
        relation_support = (len(matched_relations) / len(relations)) if relations else 1.0

        domain = self._normalize(intent.domain or "")
        scope_match = 1.0 if (not domain or self._contains(text, domain)) else (0.6 if coverage >= 0.5 else 0.0)
        time_match = self._time_score(paper.publication_year, intent)

        exclusions = [self._normalize(term) for term in intent.exclusion_concepts]
        matched_exclusions = [original for original, normalized in zip(intent.exclusion_concepts, exclusions) if self._contains(title, normalized)]
        exclusion_penalty = min(1.0, len(matched_exclusions) / max(1, len(exclusions))) if exclusions else 0.0
        metadata_quality = sum(bool(value) for value in [paper.title, paper.abstract, paper.publication_year, paper.venue]) / 4.0
        overall = max(0.0, min(1.0, 0.32 * coverage + 0.24 * relation_support + 0.16 * scope_match + 0.12 * time_match + 0.10 * metadata_quality - 0.16 * exclusion_penalty))

        strong_exclusion = bool(matched_exclusions) and (coverage < 0.5 or set(matched_exclusions) >= set(intent.exclusion_concepts))
        if strong_exclusion or (intent.time_range and time_match == 0.0) or coverage == 0.0 or overall < self.policy.adjacent_threshold:
            classification = PreliminaryRelevanceClassification.REJECTED
        elif coverage >= self.policy.core_concept_coverage and relation_support >= self.policy.core_relation_support and overall >= self.policy.core_threshold and exclusion_penalty == 0.0 and time_match > 0.0:
            classification = PreliminaryRelevanceClassification.PRELIMINARY_CORE
        else:
            classification = PreliminaryRelevanceClassification.POSSIBLE_ADJACENT

        reasons = []
        if missing: reasons.append("missing_required_concepts")
        if intent.relation_requirements and not matched_relations: reasons.append("relation_not_supported")
        if intent.time_range and time_match == 0.0: reasons.append("outside_time_range")
        if matched_exclusions: reasons.append("excluded_scope")
        if metadata_quality < 0.5: reasons.append("metadata_incomplete")
        if not reasons: reasons.append("metadata_features_supported")
        return MetadataRelevanceAssessment(paper_id=paper.id, classification=classification, required_concept_coverage=coverage, relation_support=relation_support, scope_match=scope_match, time_match=time_match, exclusion_penalty=exclusion_penalty, metadata_quality=metadata_quality, overall_score=overall, matched_concepts=matched, missing_concepts=missing, matched_relations=matched_relations, matched_exclusions=matched_exclusions, reasons=reasons)

    def assess_many(self, papers: Iterable[PaperCandidate], intent: ResearchIntent) -> list[MetadataRelevanceAssessment]:
        return [self.assess(paper, intent) for paper in papers]

    @classmethod
    def _normalize(cls, value: str) -> str:
        value = unicodedata.normalize("NFKC", value).casefold().replace("-", " ")
        return " ".join(cls._WORD_RE.findall(value))

    @classmethod
    def _contains(cls, text: str, term: str) -> bool:
        if not term:
            return False
        return term in text

    @classmethod
    def _relation_supported(cls, text: str, relation: str, concepts: list[str]) -> bool:
        relation_tokens = [token for token in cls._WORD_RE.findall(relation) if token not in cls._STOP and token not in {part for concept in concepts for part in concept.split()}]
        if relation and relation in text:
            return True
        if not relation_tokens:
            return False
        return all(token in text for token in relation_tokens) and all(cls._contains(text, concept) for concept in concepts)

    @staticmethod
    def _time_score(year: int | None, intent: ResearchIntent) -> float:
        if intent.time_range is None: return 1.0
        if year is None: return 0.5
        start, end = intent.time_range.start_year, intent.time_range.end_year
        if start is not None and year < start: return 0.0
        if end is not None and year > end: return 0.0
        return 1.0
