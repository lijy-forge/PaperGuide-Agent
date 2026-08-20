"""Orchestration, scoring, claim construction, and verified-analysis filtering."""

from collections.abc import Iterable
from uuid import UUID

from paperpilot.analysis import PaperAnalysisResult
from paperpilot.document import Document
from paperpilot.domain import EvidenceType
from paperpilot.prompts import EVIDENCE_VERIFIER_PROMPT_VERSION

from .conflicts import EvidenceConflictDetector
from .deterministic import DeterministicEvidenceChecker
from .exceptions import (
    LLMVerificationError,
    VerificationConflictError,
    VerificationInputError,
)
from .llm_verifier import LLMEvidenceVerifier
from .models import (
    DeterministicCheckResult,
    EvidenceClaim,
    EvidenceVerificationDecision,
    EvidenceVerificationResult,
    NumericConsistencyResult,
    SupportLevel,
    VerificationStatus,
    VerifiedEvidence,
    VerifiedPaperAnalysisResult,
)


def build_evidence_claims(analysis: PaperAnalysisResult) -> list[EvidenceClaim]:
    """Build one stable claim per evidence item from its mapped normalized fact.

    Summary-level evidence IDs are many-to-many references. Expanding every method
    evidence across the method summary and every innovation creates a Cartesian
    product and asks one quote to support unrelated claims. Verification therefore
    operates on the quote-specific normalized fact while retaining the source role.
    """

    evidence_by_id = {item.id: item for item in analysis.evidence}
    method_ids = set(analysis.method_summary.evidence_ids)
    experiment_ids = set(analysis.experiment_summary.evidence_ids)
    for evidence_id in method_ids:
        if evidence_id not in evidence_by_id:
            raise VerificationInputError(
                f"method references missing Evidence ID {evidence_id}"
            )
    for evidence_id in experiment_ids:
        if evidence_id not in evidence_by_id:
            raise VerificationInputError(
                f"experiment references missing Evidence ID {evidence_id}"
            )

    claims: list[EvidenceClaim] = []
    for evidence in analysis.evidence:
        roles: list[str] = []
        if evidence.id in method_ids:
            roles.append("method")
        if evidence.id in experiment_ids:
            roles.append("experiment")
        role = "_".join(roles) if roles else "evidence"
        claims.append(
            EvidenceClaim(
                evidence=evidence,
                claim=evidence.normalized_fact,
                claim_type=f"{role}_evidence",
                source_field=f"{role}.evidence",
            )
        )
    return claims


class VerificationScorer:
    """Deterministic score formula independent of LLM-provided aggregate scores."""

    BASE_SCORES = {
        (VerificationStatus.VERIFIED, SupportLevel.DIRECT): 1.0,
        (VerificationStatus.VERIFIED, SupportLevel.DERIVED): 0.85,
        (VerificationStatus.VERIFIED, SupportLevel.INFERENCE): 0.4,
        (VerificationStatus.PARTIALLY_SUPPORTED, SupportLevel.DIRECT): 0.6,
        (VerificationStatus.PARTIALLY_SUPPORTED, SupportLevel.DERIVED): 0.6,
        (VerificationStatus.PARTIALLY_SUPPORTED, SupportLevel.INFERENCE): 0.4,
    }
    MISSING_NUMBER_PENALTY = 0.7
    UNIT_DIRECTION_PENALTY = 0.8
    OVERCLAIM_PENALTY = 0.75

    @classmethod
    def score_item(cls, item: VerifiedEvidence) -> float:
        """Score one item using status, support, consistency, and penalties."""

        base = cls.BASE_SCORES.get((item.status, item.support_level), 0.0)
        score = base * item.entailment_score
        if item.numeric_consistency.missing_numbers:
            score *= cls.MISSING_NUMBER_PENALTY
        if item.numeric_consistency.unit_matches is False:
            score *= cls.UNIT_DIRECTION_PENALTY
        if item.numeric_consistency.direction_matches is False:
            score *= cls.UNIT_DIRECTION_PENALTY
        if item.overclaim_detected:
            score *= cls.OVERCLAIM_PENALTY
        score *= 1.0 - item.contradiction_score
        return max(0.0, min(1.0, score))

    @classmethod
    def score_result(cls, items: list[VerifiedEvidence]) -> float:
        """Return the arithmetic mean of deterministic per-item scores."""

        if not items:
            return 0.0
        return sum(cls.score_item(item) for item in items) / len(items)


class EvidenceVerifier:
    """Verify all explicit evidence claims with per-item failure isolation.

    Typical flow: ``PaperReader.analyze(document)``, then ``verify(analysis,
    document)``, followed by ``apply_verification(analysis, verification)``.
    """

    def __init__(
        self,
        llm_verifier: LLMEvidenceVerifier,
        deterministic_checker: DeterministicEvidenceChecker,
        conflict_detector: EvidenceConflictDetector | None = None,
    ):
        self.llm_verifier = llm_verifier
        self.deterministic_checker = deterministic_checker
        self.conflict_detector = conflict_detector or EvidenceConflictDetector()

    def verify(
        self, analysis: PaperAnalysisResult, document: Document
    ) -> EvidenceVerificationResult:
        """Verify one paper while isolating failures of individual evidence claims."""

        if analysis.paper_id != document.paper_id:
            raise VerificationInputError("analysis and document paper_id do not match")
        claims = build_evidence_claims(analysis)
        items: list[VerifiedEvidence] = []
        batch_warnings: list[str] = []
        for claim in claims:
            try:
                deterministic = self.deterministic_checker.check(claim, document)
            except Exception as error:
                deterministic = self._deterministic_failure(type(error).__name__)
            if deterministic.hard_reject:
                decision = self._hard_reject_decision(claim, deterministic.warnings)
            else:
                try:
                    decision = self.llm_verifier.verify(claim, deterministic, document)
                except LLMVerificationError as error:
                    decision = self._failure_decision(claim, error)
            decision = self._merge_deterministic(decision, deterministic.numeric_consistency)
            evidence = claim.evidence.model_copy(
                update={"evidence_type": EvidenceType(decision.support_level.value)},
                deep=True,
            )
            items.append(
                VerifiedEvidence(
                    evidence=evidence,
                    claim=claim.claim,
                    claim_type=claim.claim_type,
                    source_field=claim.source_field,
                    status=decision.status,
                    support_level=decision.support_level,
                    entailment_score=decision.entailment_score,
                    contradiction_score=decision.contradiction_score,
                    overclaim_detected=decision.overclaim_detected,
                    numeric_consistency=deterministic.numeric_consistency,
                    reasoning=decision.reasoning,
                    corrected_claim=decision.corrected_claim,
                    warnings=self._stable_unique(
                        [*deterministic.warnings, *decision.warnings]
                    ),
                    verifier_model=self.llm_verifier.model_name,
                    prompt_version=EVIDENCE_VERIFIER_PROMPT_VERSION,
                )
            )

        try:
            conflicts = self.conflict_detector.detect(items)
        except Exception as error:
            raise VerificationConflictError(
                f"evidence conflict detection failed: {type(error).__name__}"
            ) from error
        conflict_ids = {key for conflict in conflicts for key in conflict.evidence_ids}
        if conflict_ids:
            items = [
                item.model_copy(
                    update={
                        "status": VerificationStatus.CONFLICTED,
                        "warnings": self._stable_unique(
                            [*item.warnings, "Evidence participates in a detected conflict."]
                        ),
                    },
                    deep=True,
                )
                if item.evidence.id in conflict_ids
                else item
                for item in items
            ]
        for item in items:
            batch_warnings.extend(item.warnings)
        for conflict in conflicts:
            batch_warnings.extend(conflict.warnings)

        accepted, rejected, conflicted = self._categorize_ids(items)
        return EvidenceVerificationResult(
            paper_id=analysis.paper_id,
            verified_evidence=items,
            accepted_evidence_ids=accepted,
            rejected_evidence_ids=rejected,
            conflicted_evidence_ids=conflicted,
            conflicts=conflicts,
            warnings=self._stable_unique(batch_warnings),
            verification_score=VerificationScorer.score_result(items),
            total_evidence=len(items),
            total_verified=sum(item.status is VerificationStatus.VERIFIED for item in items),
            total_partial=sum(
                item.status is VerificationStatus.PARTIALLY_SUPPORTED for item in items
            ),
            total_rejected=sum(item.status is VerificationStatus.REJECTED for item in items),
            total_conflicted=sum(
                item.status is VerificationStatus.CONFLICTED for item in items
            ),
        )

    @staticmethod
    def _hard_reject_decision(
        claim: EvidenceClaim, warnings: list[str]
    ) -> EvidenceVerificationDecision:
        return EvidenceVerificationDecision(
            evidence_id=claim.evidence.id,
            claim=claim.claim,
            support_level=SupportLevel.UNSUPPORTED,
            status=VerificationStatus.REJECTED,
            entailment_score=0.0,
            contradiction_score=0.0,
            overclaim_detected=False,
            reasoning="Deterministic source-location validation failed.",
            warnings=warnings,
        )

    @staticmethod
    def _deterministic_failure(error_type: str) -> DeterministicCheckResult:
        warning = f"Deterministic verification error: {error_type}."
        return DeterministicCheckResult(
            location_valid=False,
            quote_valid=False,
            numeric_consistency=NumericConsistencyResult(
                claim_numbers=[],
                quote_numbers=[],
                missing_numbers=[],
                unit_matches=None,
                direction_matches=None,
                warnings=[warning],
            ),
            hard_reject=True,
            warnings=[warning],
        )

    @staticmethod
    def _failure_decision(
        claim: EvidenceClaim, error: LLMVerificationError
    ) -> EvidenceVerificationDecision:
        return EvidenceVerificationDecision(
            evidence_id=claim.evidence.id,
            claim=claim.claim,
            support_level=SupportLevel.UNSUPPORTED,
            status=VerificationStatus.REJECTED,
            entailment_score=0.0,
            contradiction_score=0.0,
            overclaim_detected=False,
            reasoning="Semantic verification failed for this evidence claim.",
            warnings=[f"Verification error: {type(error).__name__}."],
        )

    @staticmethod
    def _merge_deterministic(
        decision: EvidenceVerificationDecision,
        numeric: NumericConsistencyResult,
    ) -> EvidenceVerificationDecision:
        update = {}
        if numeric.direction_matches is False:
            update = {
                "status": VerificationStatus.CONFLICTED,
                "contradiction_score": max(decision.contradiction_score, 0.8),
                "overclaim_detected": True,
            }
        elif (
            decision.status is VerificationStatus.VERIFIED
            and (numeric.missing_numbers or numeric.unit_matches is False)
        ):
            update = {
                "status": VerificationStatus.PARTIALLY_SUPPORTED,
                "overclaim_detected": True,
            }
        return decision.model_copy(update=update, deep=True) if update else decision

    @staticmethod
    def _categorize_ids(
        items: list[VerifiedEvidence],
    ) -> tuple[list[UUID], list[UUID], list[UUID]]:
        statuses: dict[UUID, set[VerificationStatus]] = {}
        order: list[UUID] = []
        for item in items:
            if item.evidence.id not in statuses:
                order.append(item.evidence.id)
            statuses.setdefault(item.evidence.id, set()).add(item.status)
        conflicted = [
            key for key in order if VerificationStatus.CONFLICTED in statuses[key]
        ]
        supported_statuses = {
            VerificationStatus.VERIFIED,
            VerificationStatus.PARTIALLY_SUPPORTED,
        }
        accepted = [
            key
            for key in order
            if key not in conflicted and statuses[key] & supported_statuses
        ]
        rejected = [
            key for key in order if key not in conflicted and key not in accepted
        ]
        return accepted, rejected, conflicted

    @staticmethod
    def _stable_unique(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))


def apply_verification(
    analysis: PaperAnalysisResult,
    verification: EvidenceVerificationResult,
) -> VerifiedPaperAnalysisResult:
    """Filter summaries conservatively without modifying the original analysis."""

    if analysis.paper_id != verification.paper_id:
        raise VerificationInputError("analysis and verification paper_id do not match")
    accepted = set(verification.accepted_evidence_ids)
    if not accepted:
        raise VerificationInputError("analysis has no accepted evidence")
    method_ids = [key for key in analysis.method_summary.evidence_ids if key in accepted]
    experiment_ids = [
        key for key in analysis.experiment_summary.evidence_ids if key in accepted
    ]
    warnings = list(verification.warnings)
    if method_ids:
        verified_method = analysis.method_summary.model_copy(
            update={"evidence_ids": method_ids}, deep=True
        )
    else:
        verified_method = analysis.method_summary.model_copy(
            update={
                "name": None,
                "problem": None,
                "summary": "No verified method summary is available.",
                "innovations": [],
                "limitations": [],
                "evidence_ids": [],
                "confidence": 0.0,
            },
            deep=True,
        )
        warnings.append(
            "Method fields were removed because no method evidence was accepted."
        )
    experiment_update = {"evidence_ids": experiment_ids}
    if not experiment_ids:
        experiment_update.update(
            {"datasets": [], "metrics": {}, "baselines": [], "findings": []}
        )
        warnings.append(
            "Experiment fields were removed because no experiment evidence was accepted."
        )
    warnings.append(
        "Contributions and limitations were not retained because their per-item "
        "evidence associations are unavailable."
    )
    return VerifiedPaperAnalysisResult(
        original_analysis=analysis.model_copy(deep=True),
        verification=verification.model_copy(deep=True),
        verified_method_summary=verified_method,
        verified_experiment_summary=analysis.experiment_summary.model_copy(
            update=experiment_update, deep=True
        ),
        verified_contributions=[],
        verified_limitations=[],
        warnings=list(dict.fromkeys(warnings)),
    )
