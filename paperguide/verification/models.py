"""Pydantic contracts for evidence claims, decisions, and verified analysis."""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paperguide.analysis import PaperAnalysisResult
from paperguide.domain import Evidence, ExperimentSummary, MethodSummary


class VerificationStatus(str, Enum):
    """Lifecycle and final states of one claim-evidence verification."""

    PENDING = "pending"
    VERIFIED = "verified"
    PARTIALLY_SUPPORTED = "partially_supported"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"


class SupportLevel(str, Enum):
    """Semantic relationship between a quote and a claim."""

    DIRECT = "direct"
    DERIVED = "derived"
    INFERENCE = "inference"
    UNSUPPORTED = "unsupported"


class NumericConsistencyResult(BaseModel):
    """Deterministic comparison of numbers, units, and direction language."""

    model_config = ConfigDict(extra="forbid")

    claim_numbers: list[str]
    quote_numbers: list[str]
    missing_numbers: list[str]
    unit_matches: bool | None
    direction_matches: bool | None
    warnings: list[str]


class EvidenceClaim(BaseModel):
    """An explicit claim associated with an existing Evidence object."""

    model_config = ConfigDict(extra="forbid")

    evidence: Evidence
    claim: str
    claim_type: str | None = None
    source_field: str | None = None

    @field_validator("claim")
    @classmethod
    def validate_claim(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("claim must not be empty")
        return value


class DeterministicCheckResult(BaseModel):
    """Location and literal-consistency checks performed without an LLM."""

    model_config = ConfigDict(extra="forbid")

    location_valid: bool
    quote_valid: bool
    numeric_consistency: NumericConsistencyResult
    hard_reject: bool
    warnings: list[str]


class EvidenceVerificationAssessment(BaseModel):
    """LLM-owned semantic fields without trusted evidence identity fields."""

    model_config = ConfigDict(extra="forbid")

    support_level: SupportLevel
    status: VerificationStatus
    entailment_score: float = Field(ge=0.0, le=1.0)
    contradiction_score: float = Field(ge=0.0, le=1.0)
    overclaim_detected: bool
    reasoning: str
    corrected_claim: str | None = None
    warnings: list[str]

    @field_validator("support_level", "status", mode="before")
    @classmethod
    def normalize_enum_value(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().casefold().replace("-", "_").replace(" ", "_")
        return value

    @field_validator("reasoning")
    @classmethod
    def validate_reasoning(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("verification reasoning must not be empty")
        return value


class EvidenceVerificationDecision(BaseModel):
    """Strict structured output expected from the semantic verifier LLM."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    claim: str
    support_level: SupportLevel
    status: VerificationStatus
    entailment_score: float = Field(ge=0.0, le=1.0)
    contradiction_score: float = Field(ge=0.0, le=1.0)
    overclaim_detected: bool
    reasoning: str
    corrected_claim: str | None = None
    warnings: list[str]

    @field_validator("support_level", "status", mode="before")
    @classmethod
    def normalize_enum_value(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().casefold().replace("-", "_").replace(" ", "_")
        return value

    @field_validator("claim", "reasoning")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("verification decision text must not be empty")
        return value

    @model_validator(mode="after")
    def validate_decision_state(self) -> "EvidenceVerificationDecision":
        if (
            self.status is VerificationStatus.VERIFIED
            and self.support_level is SupportLevel.UNSUPPORTED
        ):
            raise ValueError("verified evidence cannot be unsupported")
        if (
            self.status is VerificationStatus.REJECTED
            and self.support_level is not SupportLevel.UNSUPPORTED
            and self.entailment_score > 0.2
        ):
            raise ValueError("rejected evidence must be unsupported or extremely weak")
        if self.status is VerificationStatus.CONFLICTED:
            explanation = " ".join([self.reasoning, *self.warnings]).casefold()
            if self.contradiction_score <= 0 and not any(
                term in explanation for term in ("conflict", "contradict", "冲突", "矛盾")
            ):
                raise ValueError("conflicted evidence must explain the conflict")
        return self


class VerifiedEvidence(BaseModel):
    """One claim-evidence pair after deterministic and semantic verification."""

    model_config = ConfigDict(extra="forbid")

    evidence: Evidence
    claim: str
    claim_type: str | None = None
    source_field: str | None = None
    status: VerificationStatus
    support_level: SupportLevel
    entailment_score: float = Field(ge=0.0, le=1.0)
    contradiction_score: float = Field(ge=0.0, le=1.0)
    overclaim_detected: bool
    numeric_consistency: NumericConsistencyResult
    reasoning: str
    corrected_claim: str | None = None
    warnings: list[str]
    verifier_model: str | None = None
    prompt_version: str
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("claim", "reasoning", "prompt_version")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("verified evidence text must not be empty")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> "VerifiedEvidence":
        if self.status is VerificationStatus.PENDING:
            raise ValueError("verified evidence cannot remain pending")
        if (
            self.status is VerificationStatus.VERIFIED
            and self.support_level is SupportLevel.UNSUPPORTED
        ):
            raise ValueError("verified evidence cannot be unsupported")
        return self


class ConflictRecord(BaseModel):
    """A conservative conflict detected among verified claim-evidence pairs."""

    model_config = ConfigDict(extra="forbid")

    conflict_id: UUID = Field(default_factory=uuid4)
    evidence_ids: list[UUID]
    claims: list[str]
    conflict_type: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str]


class EvidenceVerificationResult(BaseModel):
    """Paper-level verification output with disjoint evidence-ID categories."""

    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    verified_evidence: list[VerifiedEvidence]
    accepted_evidence_ids: list[UUID]
    rejected_evidence_ids: list[UUID]
    conflicted_evidence_ids: list[UUID]
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    warnings: list[str]
    verification_score: float = Field(ge=0.0, le=1.0)
    total_evidence: int = Field(ge=0)
    total_verified: int = Field(ge=0)
    total_partial: int = Field(ge=0)
    total_rejected: int = Field(ge=0)
    total_conflicted: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_result(self) -> "EvidenceVerificationResult":
        if any(item.evidence.paper_id != self.paper_id for item in self.verified_evidence):
            raise ValueError("all verified evidence must belong to result paper_id")
        lists = [
            self.accepted_evidence_ids,
            self.rejected_evidence_ids,
            self.conflicted_evidence_ids,
        ]
        if any(len(values) != len(set(values)) for values in lists):
            raise ValueError("evidence ID lists must not contain duplicates")
        accepted, rejected, conflicted = map(set, lists)
        if accepted & rejected or accepted & conflicted or rejected & conflicted:
            raise ValueError("evidence ID categories must be disjoint")

        counts = {
            VerificationStatus.VERIFIED: self.total_verified,
            VerificationStatus.PARTIALLY_SUPPORTED: self.total_partial,
            VerificationStatus.REJECTED: self.total_rejected,
            VerificationStatus.CONFLICTED: self.total_conflicted,
        }
        if self.total_evidence != len(self.verified_evidence):
            raise ValueError("total_evidence must match verified_evidence")
        for status, expected in counts.items():
            actual = sum(item.status is status for item in self.verified_evidence)
            if actual != expected:
                raise ValueError(f"count for {status.value} is inconsistent")
        if any(item.status is VerificationStatus.PENDING for item in self.verified_evidence):
            raise ValueError("completed verification cannot contain pending evidence")

        status_by_id: dict[UUID, set[VerificationStatus]] = {}
        for item in self.verified_evidence:
            status_by_id.setdefault(item.evidence.id, set()).add(item.status)
        expected_conflicted = {
            key for key, statuses in status_by_id.items() if VerificationStatus.CONFLICTED in statuses
        }
        supported_statuses = {
            VerificationStatus.VERIFIED,
            VerificationStatus.PARTIALLY_SUPPORTED,
        }
        expected_accepted = {
            key
            for key, statuses in status_by_id.items()
            if key not in expected_conflicted and statuses & supported_statuses
        }
        expected_rejected = set(status_by_id) - expected_conflicted - expected_accepted
        if conflicted != expected_conflicted:
            raise ValueError("conflicted_evidence_ids are inconsistent")
        if rejected != expected_rejected:
            raise ValueError("rejected_evidence_ids are inconsistent")
        if accepted != expected_accepted:
            raise ValueError("accepted_evidence_ids are inconsistent")
        return self


class VerifiedPaperAnalysisResult(BaseModel):
    """Paper analysis filtered to evidence accepted by the verifier."""

    model_config = ConfigDict(extra="forbid")

    original_analysis: PaperAnalysisResult
    verification: EvidenceVerificationResult
    verified_method_summary: MethodSummary
    verified_experiment_summary: ExperimentSummary
    verified_contributions: list[str]
    verified_limitations: list[str]
    warnings: list[str]

    @model_validator(mode="after")
    def validate_paper_ids(self) -> "VerifiedPaperAnalysisResult":
        paper_id = self.original_analysis.paper_id
        if self.verification.paper_id != paper_id:
            raise ValueError("verification paper_id must match original analysis")
        if self.verified_method_summary.paper_id != paper_id:
            raise ValueError("verified method paper_id must match original analysis")
        if self.verified_experiment_summary.paper_id != paper_id:
            raise ValueError("verified experiment paper_id must match original analysis")
        return self
