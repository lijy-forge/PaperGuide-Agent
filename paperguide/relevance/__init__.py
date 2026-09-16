"""Public retrieval-planning contracts and services."""

from .expansion import DeterministicQueryExpansionService, LLMQueryExpansionService
from .models import QueryExpansionOutput, QueryVariant, ResearchIntent, RetrievalBudget, RetrievalPlan, TimeRange
from .gate import MetadataRelevanceAssessment, MetadataRelevanceGate, MetadataRelevancePolicy, PreliminaryRelevanceClassification
from .pool import CandidatePoolResult, CandidateRelevanceRecord, CandidateSelectionPolicy, MultiQueryRetrievalService, RetrievalAudit
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
from .planners import DeterministicResearchIntentPlanner, StructuredLLMResearchIntentPlanner
from .protocols import QueryExpansionProtocol, ResearchIntentPlannerProtocol
from .service import RetrievalPlanService
from .diagnostics import PlanningStageDiagnostic, classify_planning_failure
from .language import language_from_question, normalize_query_language
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
