"""Deterministic statement-to-verified-evidence traceability models and service."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from enum import Enum
from typing import TYPE_CHECKING, Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from paperpilot.domain import PaperCandidate
if TYPE_CHECKING:
    from paperpilot.verification import VerifiedPaperAnalysisResult

from .models import PaperAnalysisResult


class StatementKind(str, Enum):
    CONTRIBUTION = "contribution"
    INNOVATION = "innovation"
    LIMITATION = "limitation"
    FINDING = "finding"


class StatementSupportStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONFLICTED = "conflicted"
    UNSUPPORTED = "unsupported"
    UNMAPPED = "unmapped"


class LimitationBasis(str, Enum):
    AUTHOR_STATED = "author_stated"
    EVIDENCE_BOUND_OBSERVATION = "evidence_bound_observation"
    READER_INFERENCE = "reader_inference"


class StatementLinkingBudget(BaseModel):
    """Bound statement enrichment output without changing Reader output limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_contributions: int = Field(default=20, ge=1, le=100)
    max_innovations: int = Field(default=20, ge=1, le=100)
    max_limitations: int = Field(default=20, ge=1, le=100)
    max_findings: int = Field(default=20, ge=1, le=100)


class EvidenceLinkedStatement(BaseModel):
    """One Reader statement linked to existing Evidence keys and verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement_key: str
    kind: StatementKind
    text: str
    support_status: StatementSupportStatus
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_keys: list[str] = Field(default_factory=list)
    contradicting_evidence_keys: list[str] = Field(default_factory=list)
    unsupported_evidence_keys: list[str] = Field(default_factory=list)
    is_evidence_grounded: bool
    reasons: list[str] = Field(default_factory=list)
    statement_basis: LimitationBasis | None = None


class StatementLinkingStatistics(BaseModel):
    """Counts for audit and future report-quality metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_statements: int = Field(ge=0)
    supported_statements: int = Field(ge=0)
    partially_supported_statements: int = Field(ge=0)
    conflicted_statements: int = Field(ge=0)
    unsupported_statements: int = Field(ge=0)
    unmapped_statements: int = Field(ge=0)
    grounded_statements: int = Field(ge=0)
    contribution_count: int = Field(ge=0)
    innovation_count: int = Field(ge=0)
    limitation_count: int = Field(ge=0)
    finding_count: int = Field(ge=0)


class EvidenceLinkedPaperAnalysis(BaseModel):
    """Reader analysis enriched with statement-level evidence traceability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    paper_id: UUID
    contributions: list[EvidenceLinkedStatement]
    innovations: list[EvidenceLinkedStatement]
    limitations: list[EvidenceLinkedStatement]
    findings: list[EvidenceLinkedStatement]
    linking_statistics: StatementLinkingStatistics
    warnings: list[str]


class EvidenceLinkingService:
    """Link existing verified Evidence without making another LLM call."""

    _TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
    _STOP = {"a", "an", "and", "or", "the", "of", "to", "for", "with", "in", "on", "is", "are", "this", "that"}

    def __init__(self, budget: StatementLinkingBudget | None = None):
        self.budget = budget or StatementLinkingBudget()

    def link(
        self,
        analysis: PaperAnalysisResult,
        verified_result: VerifiedPaperAnalysisResult,
        paper: PaperCandidate | None = None,
    ) -> EvidenceLinkedPaperAnalysis:
        if analysis.paper_id != verified_result.original_analysis.paper_id:
            raise ValueError("analysis and verification paper_id must match")
        verified = list(verified_result.verification.verified_evidence)
        evidence_by_id = {str(item.evidence.id): item for item in verified}
        fingerprint = self._paper_fingerprint(paper, analysis)
        warnings: list[str] = []
        if any(item.evidence.paper_id != analysis.paper_id for item in verified):
            warnings.append("CROSS_PAPER_EVIDENCE_LINK")
        specs = [
            (StatementKind.CONTRIBUTION, analysis.contributions, self.budget.max_contributions, list(analysis.method_summary.evidence_ids)),
            (StatementKind.INNOVATION, analysis.method_summary.innovations, self.budget.max_innovations, list(analysis.method_summary.evidence_ids)),
            (StatementKind.LIMITATION, analysis.limitations, self.budget.max_limitations, list(analysis.method_summary.evidence_ids)),
            (StatementKind.FINDING, analysis.experiment_summary.findings, self.budget.max_findings, list(analysis.experiment_summary.evidence_ids)),
        ]
        linked: dict[StatementKind, list[EvidenceLinkedStatement]] = {}
        for kind, source_texts, limit, preferred_ids in specs:
            texts = source_texts[:limit]
            if len(source_texts) > len(texts):
                warnings.append("STATEMENT_LINKING_TRUNCATED")
            if any(str(value) not in evidence_by_id for value in preferred_ids):
                warnings.append("DANGLING_EVIDENCE_KEY")
            linked[kind] = [self._link_statement(fingerprint, kind, text, preferred_ids, evidence_by_id, analysis.paper_id) for text in self._stable_texts(texts)]
        all_statements = [item for items in linked.values() for item in items]
        statistics = StatementLinkingStatistics(
            total_statements=len(all_statements),
            supported_statements=sum(item.support_status is StatementSupportStatus.SUPPORTED for item in all_statements),
            partially_supported_statements=sum(item.support_status is StatementSupportStatus.PARTIALLY_SUPPORTED for item in all_statements),
            conflicted_statements=sum(item.support_status is StatementSupportStatus.CONFLICTED for item in all_statements),
            unsupported_statements=sum(item.support_status is StatementSupportStatus.UNSUPPORTED for item in all_statements),
            unmapped_statements=sum(item.support_status is StatementSupportStatus.UNMAPPED for item in all_statements),
            grounded_statements=sum(item.is_evidence_grounded for item in all_statements),
            contribution_count=len(linked[StatementKind.CONTRIBUTION]),
            innovation_count=len(linked[StatementKind.INNOVATION]),
            limitation_count=len(linked[StatementKind.LIMITATION]),
            finding_count=len(linked[StatementKind.FINDING]),
        )
        if statistics.unmapped_statements or statistics.unsupported_statements:
            warnings.append("STATEMENT_LINKING_INCOMPLETE")
        return EvidenceLinkedPaperAnalysis(
            paper_id=analysis.paper_id,
            contributions=linked[StatementKind.CONTRIBUTION],
            innovations=linked[StatementKind.INNOVATION],
            limitations=linked[StatementKind.LIMITATION],
            findings=linked[StatementKind.FINDING],
            linking_statistics=statistics,
            warnings=list(dict.fromkeys(warnings)),
        )

    def _link_statement(self, fingerprint, kind, text, preferred_ids, evidence_by_id, paper_id):
        from paperpilot.verification import VerificationStatus

        normalized = self._normalize(text)
        candidates = []
        for key, item in evidence_by_id.items():
            if item.evidence.paper_id != paper_id:
                continue
            evidence_text = self._normalize(f"{item.claim} {item.evidence.quote} {item.evidence.normalized_fact}")
            score = self._overlap(normalized, evidence_text)
            # Summary evidence IDs constrain the candidate set, but never
            # support an unrelated statement on their own.
            if key in {str(value) for value in preferred_ids}:
                score += 0.25 if score >= 0.2 else 0
            if score >= 0.2:
                candidates.append((score, key, item))
        candidates.sort(key=lambda value: (-value[0], value[1]))
        supporting, contradicting, unsupported = [], [], []
        for _, key, item in candidates:
            if item.status in {VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_SUPPORTED}:
                supporting.append(key)
            elif item.status is VerificationStatus.CONFLICTED:
                contradicting.append(key)
            else:
                unsupported.append(key)
        supporting = list(dict.fromkeys(supporting))
        contradicting = list(dict.fromkeys(contradicting))
        unsupported = list(dict.fromkeys(unsupported))
        if supporting and contradicting:
            status = StatementSupportStatus.CONFLICTED
        elif supporting:
            status = StatementSupportStatus.PARTIALLY_SUPPORTED if any(evidence_by_id[key].status is VerificationStatus.PARTIALLY_SUPPORTED for key in supporting) else StatementSupportStatus.SUPPORTED
        elif unsupported:
            status = StatementSupportStatus.UNSUPPORTED
        else:
            status = StatementSupportStatus.UNMAPPED
        confidence = self._confidence([*supporting, *contradicting], evidence_by_id)
        if supporting:
            confidence *= min(1.0, 0.5 + 0.25 * len(supporting))
        if contradicting:
            confidence *= 0.5
        if unsupported:
            confidence *= 0.8
        grounded = status in {StatementSupportStatus.SUPPORTED, StatementSupportStatus.PARTIALLY_SUPPORTED} and bool(supporting) and any(self._has_locator(evidence_by_id[key]) for key in supporting)
        reasons = []
        if not supporting: reasons.append("NO_SUPPORTING_EVIDENCE")
        if contradicting: reasons.append("CONFLICTING_EVIDENCE")
        if unsupported: reasons.append("UNSUPPORTED_EVIDENCE")
        if grounded: reasons.append("VERIFIED_LOCATED_SUPPORT")
        return EvidenceLinkedStatement(statement_key=self._statement_key(fingerprint, kind, text), kind=kind, text=text.strip(), support_status=status, confidence=confidence, supporting_evidence_keys=supporting, contradicting_evidence_keys=contradicting, unsupported_evidence_keys=unsupported, is_evidence_grounded=grounded, reasons=reasons, statement_basis=self._basis(kind, text))

    @classmethod
    def _statement_key(cls, fingerprint, kind, text):
        return hashlib.sha256(f"{fingerprint}|{kind.value}|{cls._normalize(text)}".encode("utf-8")).hexdigest()[:32]

    @classmethod
    def _normalize(cls, text):
        text = unicodedata.normalize("NFKC", text).casefold().replace("-", " ")
        return " ".join(cls._TOKEN_RE.findall(text))

    @classmethod
    def _overlap(cls, left, right):
        left_tokens = {token for token in left.split() if token not in cls._STOP}
        right_tokens = {token for token in right.split() if token not in cls._STOP}
        return len(left_tokens & right_tokens) / max(1, len(left_tokens))

    @staticmethod
    def _has_locator(item):
        locator = item.evidence.locator
        return any(value is not None for value in [locator.section_title, locator.page_start, locator.paragraph_index, locator.char_start])

    @classmethod
    def _confidence(cls, keys, evidence_by_id):
        if not keys: return 0.0
        values = []
        for key in keys:
            item = evidence_by_id[key]
            locator = sum(value is not None for value in [item.evidence.locator.section_title, item.evidence.locator.page_start, item.evidence.locator.paragraph_index, item.evidence.locator.char_start]) / 4
            values.append(0.7 * item.entailment_score + 0.3 * locator)
        return max(0.0, min(1.0, sum(values) / len(values)))

    @staticmethod
    def _paper_fingerprint(paper, analysis):
        if paper is not None:
            for value in [paper.doi, paper.arxiv_id, paper.semantic_scholar_id, paper.openalex_id, paper.normalized_title]:
                if value and str(value).strip(): return str(value).strip().casefold()
        return str(analysis.paper_id)

    @staticmethod
    def _field_for_kind(kind):
        return {StatementKind.CONTRIBUTION: "contributions", StatementKind.INNOVATION: "innovations", StatementKind.LIMITATION: "limitations", StatementKind.FINDING: "findings"}[kind]

    @staticmethod
    def _basis(kind, text):
        if kind is not StatementKind.LIMITATION: return None
        lowered = text.casefold()
        if any(term in lowered for term in ["paper", "study", "evaluation", "experiment"]): return LimitationBasis.EVIDENCE_BOUND_OBSERVATION
        return LimitationBasis.READER_INFERENCE

    @staticmethod
    def _stable_texts(values):
        return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))
