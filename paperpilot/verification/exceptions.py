"""Exception hierarchy for independent evidence verification."""


class EvidenceVerificationError(RuntimeError):
    """Base exception for evidence-verification failures."""


class VerificationInputError(EvidenceVerificationError):
    """Raised when analysis and document inputs are incompatible."""


class DeterministicVerificationError(EvidenceVerificationError):
    """Raised when deterministic checks cannot be completed."""


class LLMVerificationError(EvidenceVerificationError):
    """Raised for safely wrapped single-evidence LLM failures."""


class VerificationConflictError(EvidenceVerificationError):
    """Raised when conflict processing itself cannot be completed."""
