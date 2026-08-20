"""Public structured paper-analysis interface for PaperPilot AI."""

from .context_builder import PaperContextBuilder, PaperContextConfig
from .evidence_mapper import EvidenceMapper
from .exceptions import (
    AnalysisLLMError,
    AnalysisLLMInvocationError,
    AnalysisLLMResponseError,
    AnalysisSchemaValidationError,
    EvidenceMappingError,
    InsufficientEvidenceError,
    PaperAnalysisError,
    PaperContextError,
)
from .llm_protocol import StructuredLLMProtocol
from .models import (
    EvidenceMappingResult,
    EvidenceReference,
    ExperimentAnalysis,
    ExperimentMetricAnalysis,
    MethodAnalysis,
    PaperAnalysisResult,
    PaperContext,
    PaperReaderOutput,
)
from .reader import PaperReader
from .statements import (
    EvidenceLinkedPaperAnalysis,
    EvidenceLinkedStatement,
    EvidenceLinkingService,
    LimitationBasis,
    StatementKind,
    StatementLinkingBudget,
    StatementLinkingStatistics,
    StatementSupportStatus,
)

__all__ = [
    "AnalysisLLMError",
    "AnalysisLLMInvocationError",
    "AnalysisLLMResponseError",
    "AnalysisSchemaValidationError",
    "EvidenceMapper",
    "EvidenceMappingError",
    "EvidenceMappingResult",
    "EvidenceReference",
    "ExperimentAnalysis",
    "ExperimentMetricAnalysis",
    "InsufficientEvidenceError",
    "MethodAnalysis",
    "PaperAnalysisError",
    "PaperAnalysisResult",
    "PaperContext",
    "PaperContextBuilder",
    "PaperContextConfig",
    "PaperContextError",
    "PaperReader",
    "PaperReaderOutput",
    "StructuredLLMProtocol",
    "EvidenceLinkedPaperAnalysis",
    "EvidenceLinkedStatement",
    "EvidenceLinkingService",
    "LimitationBasis",
    "StatementKind",
    "StatementLinkingBudget",
    "StatementLinkingStatistics",
    "StatementSupportStatus",
]
