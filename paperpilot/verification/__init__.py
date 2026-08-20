"""Public independent evidence-verification interface for PaperPilot AI."""

from .conflicts import EvidenceConflictDetector
from .deterministic import DeterministicEvidenceChecker, DeterministicEvidenceConfig
from .exceptions import (
    DeterministicVerificationError,
    EvidenceVerificationError,
    LLMVerificationError,
    VerificationConflictError,
    VerificationInputError,
)
from .llm_verifier import LLMEvidenceVerifier, LLMEvidenceVerifierConfig
from .models import (
    ConflictRecord,
    DeterministicCheckResult,
    EvidenceClaim,
    EvidenceVerificationAssessment,
    EvidenceVerificationDecision,
    EvidenceVerificationResult,
    NumericConsistencyResult,
    SupportLevel,
    VerificationStatus,
    VerifiedEvidence,
    VerifiedPaperAnalysisResult,
)
from .verifier import (
    EvidenceVerifier,
    VerificationScorer,
    apply_verification,
    build_evidence_claims,
)

__all__ = [
    "ConflictRecord",
    "DeterministicCheckResult",
    "DeterministicEvidenceChecker",
    "DeterministicEvidenceConfig",
    "DeterministicVerificationError",
    "EvidenceClaim",
    "EvidenceVerificationAssessment",
    "EvidenceConflictDetector",
    "EvidenceVerificationDecision",
    "EvidenceVerificationError",
    "EvidenceVerificationResult",
    "EvidenceVerifier",
    "LLMEvidenceVerifier",
    "LLMEvidenceVerifierConfig",
    "LLMVerificationError",
    "NumericConsistencyResult",
    "SupportLevel",
    "VerificationConflictError",
    "VerificationInputError",
    "VerificationScorer",
    "VerificationStatus",
    "VerifiedEvidence",
    "VerifiedPaperAnalysisResult",
    "apply_verification",
    "build_evidence_claims",
]
