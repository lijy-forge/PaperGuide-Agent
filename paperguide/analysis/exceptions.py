"""Exception hierarchy for structured paper analysis."""


class PaperAnalysisError(RuntimeError):
    """Base exception for PaperGuide paper-analysis failures."""


class PaperContextError(PaperAnalysisError):
    """Raised when a usable controlled paper context cannot be built."""


class EvidenceMappingError(PaperAnalysisError):
    """Raised when evidence mapping cannot be completed safely."""


class InsufficientEvidenceError(EvidenceMappingError):
    """Raised when a critical analysis has no valid supporting evidence."""


class AnalysisLLMError(PaperAnalysisError):
    """Base exception for structured LLM adapter failures."""


class AnalysisLLMInvocationError(AnalysisLLMError):
    """Raised when the configured LLM invocation fails."""


class AnalysisLLMResponseError(AnalysisLLMError):
    """Raised when an LLM response does not contain valid JSON."""


class AnalysisSchemaValidationError(AnalysisLLMError):
    """Raised when valid JSON does not satisfy the requested schema."""
