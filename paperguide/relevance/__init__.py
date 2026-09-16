"""Public retrieval-planning contracts and services."""

from .audit import (
    DedupGroupDiagnostic,
    IntentDiagnostic,
    IntentTermDiagnostic,
    MetadataCandidateDiagnostic,
    QueryDiagnostic,
    RetrievalMetadataDiagnostic,
    RetrievalOverlapDiagnostic,
    audit_hash,
    classify_text_language,
    normalize_audit_text,
    stable_paper_identity,
)
from .diagnostics import PlanningStageDiagnostic, classify_planning_failure
from .expansion import DeterministicQueryExpansionService, LLMQueryExpansionService
from .final import (
    AssessmentStatus,
    EvidenceAwareFinalRelevanceService,
    EvidenceSufficiencyAssessment,
    FinalCoreSelectionPolicy,
    FinalRelevanceAssessment,
    FinalRelevanceAudit,
    FinalRelevanceClassification,
    FinalRelevancePolicy,
    ReportMode,
)
from .gate import (
    MetadataRelevanceAssessment,
    MetadataRelevanceGate,
    MetadataRelevancePolicy,
    PreliminaryRelevanceClassification,
)
from .language import language_from_question, normalize_query_language
from .models import QueryExpansionOutput, QueryVariant, ResearchIntent, RetrievalBudget, RetrievalPlan, TimeRange
from .planners import DeterministicResearchIntentPlanner, StructuredLLMResearchIntentPlanner
from .pool import (
    CandidatePoolResult,
    CandidateRelevanceRecord,
    CandidateSelectionPolicy,
    MultiQueryRetrievalService,
    RetrievalAudit,
)
from .protocols import QueryExpansionProtocol, ResearchIntentPlannerProtocol
from .service import RetrievalPlanService

__all__ = [
    "DeterministicQueryExpansionService",
    "DeterministicResearchIntentPlanner",
    "LLMQueryExpansionService",
    "QueryExpansionOutput",
    "QueryExpansionProtocol",
    "QueryVariant",
    "ResearchIntent",
    "ResearchIntentPlannerProtocol",
    "RetrievalBudget",
    "RetrievalPlan",
    "RetrievalPlanService",
    "PlanningStageDiagnostic",
    "classify_planning_failure",
    "language_from_question",
    "normalize_query_language",
    "StructuredLLMResearchIntentPlanner",
    "TimeRange",
    "MetadataRelevanceAssessment",
    "MetadataRelevanceGate",
    "MetadataRelevancePolicy",
    "PreliminaryRelevanceClassification",
    "CandidatePoolResult",
    "CandidateRelevanceRecord",
    "CandidateSelectionPolicy",
    "MultiQueryRetrievalService",
    "RetrievalAudit",
    "AssessmentStatus",
    "EvidenceAwareFinalRelevanceService",
    "EvidenceSufficiencyAssessment",
    "FinalCoreSelectionPolicy",
    "FinalRelevanceAssessment",
    "FinalRelevanceAudit",
    "FinalRelevanceClassification",
    "FinalRelevancePolicy",
    "ReportMode",
    "DedupGroupDiagnostic",
    "IntentDiagnostic",
    "IntentTermDiagnostic",
    "MetadataCandidateDiagnostic",
    "QueryDiagnostic",
    "RetrievalMetadataDiagnostic",
    "RetrievalOverlapDiagnostic",
    "audit_hash",
    "classify_text_language",
    "normalize_audit_text",
    "stable_paper_identity",
]
