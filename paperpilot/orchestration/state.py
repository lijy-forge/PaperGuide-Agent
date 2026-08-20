"""LangGraph-ready TypedDict state contract without a LangGraph dependency."""

from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from typing_extensions import NotRequired, TypedDict

from paperpilot.analysis import EvidenceLinkedPaperAnalysis, PaperAnalysisResult
from paperpilot.document import Document, DocumentIngestionResult
from paperpilot.domain import PaperCandidate, ResearchConfig
from paperpilot.pipeline import SearchResult
from paperpilot.verification import (
    EvidenceVerificationResult,
    VerifiedPaperAnalysisResult,
)
from paperpilot.relevance import (
    CandidateRelevanceRecord,
    EvidenceSufficiencyAssessment,
    FinalRelevanceAssessment,
    FinalRelevanceAudit,
    ReportMode,
    RetrievalAudit,
    RetrievalPlan,
)

from .enums import NextAction, ResearchStep
from .errors import PaperStageRecord, ResearchError, StateValidationError


class ResearchState(TypedDict):
    """Checkpoint-serializable state shared by future orchestration nodes."""

    question: str
    research_config: ResearchConfig
    papers: list[PaperCandidate]
    documents: dict[str, Document]
    analyses: dict[str, PaperAnalysisResult]
    verification_results: dict[str, EvidenceVerificationResult]
    verified_results: dict[str, VerifiedPaperAnalysisResult]
    errors: list[ResearchError]
    current_step: ResearchStep
    next_action: NextAction
    search_result: NotRequired[SearchResult | None]
    ingestion_result: NotRequired[DocumentIngestionResult | None]
    paper_status: NotRequired[dict[str, PaperStageRecord]]
    warnings: NotRequired[list[str]]
    attempts: NotRequired[dict[str, int]]
    quality_summary: NotRequired[dict[str, object]]
    run_id: NotRequired[UUID]
    terminal_reason: NotRequired[str | None]
    retrieval_plan: NotRequired[RetrievalPlan | None]
    retrieval_audit: NotRequired[RetrievalAudit | None]
    candidate_relevance: NotRequired[list[CandidateRelevanceRecord]]
    final_relevance: NotRequired[dict[str, FinalRelevanceAssessment]]
    final_relevance_audit: NotRequired[FinalRelevanceAudit | None]
    evidence_sufficiency: NotRequired[EvidenceSufficiencyAssessment | None]
    report_mode: NotRequired[ReportMode | None]
    evidence_linked_analysis: NotRequired[dict[str, EvidenceLinkedPaperAnalysis]]


_STATE_ADAPTER = TypeAdapter(ResearchState)


def create_initial_state(
    question: str, research_config: ResearchConfig
) -> ResearchState:
    """Create and validate an empty research workflow state."""

    normalized_question = question.strip()
    state: ResearchState = {
        "question": normalized_question,
        "research_config": research_config,
        "papers": [],
        "documents": {},
        "analyses": {},
        "verification_results": {},
        "verified_results": {},
        "errors": [],
        "current_step": ResearchStep.INITIALIZED,
        "next_action": NextAction.RETRIEVE,
        "search_result": None,
        "ingestion_result": None,
        "paper_status": {},
        "warnings": [],
        "attempts": {},
        "quality_summary": {},
        "run_id": uuid4(),
        "terminal_reason": None,
    }
    return validate_state(state)


def validate_state(state: ResearchState) -> ResearchState:
    """Validate state types and cross-object paper associations."""

    try:
        validated = _STATE_ADAPTER.validate_python(state)
    except ValidationError as error:
        raise StateValidationError("research state does not satisfy its type contract") from error

    if validated["question"] != validated["research_config"].question:
        raise StateValidationError("question must match research_config.question")

    paper_ids = [paper.id for paper in validated["papers"]]
    if len(paper_ids) != len(set(paper_ids)):
        raise StateValidationError("papers must not contain duplicate paper_id values")

    documents = validated["documents"]
    for key, document in documents.items():
        if key != str(document.paper_id):
            raise StateValidationError("document key must equal Document.paper_id")

    analyses = validated["analyses"]
    for key, analysis in analyses.items():
        if key not in documents:
            raise StateValidationError("analysis must have a corresponding document")
        if key != str(analysis.paper_id):
            raise StateValidationError("analysis key must equal PaperAnalysisResult.paper_id")

    for key, result in validated["verification_results"].items():
        if key not in analyses or key != str(result.paper_id):
            raise StateValidationError(
                "verification result must have a corresponding analysis"
            )

    for key, result in validated["verified_results"].items():
        if key not in analyses or key != str(result.original_analysis.paper_id):
            raise StateValidationError(
                "verified result must have a corresponding analysis"
            )

    for key, attempt in validated.get("attempts", {}).items():
        if attempt < 0:
            raise StateValidationError(f"attempt count for {key!r} cannot be negative")

    for key, record in validated.get("paper_status", {}).items():
        if key != str(record.paper_id):
            raise StateValidationError("paper_status key must equal record paper_id")
    return validated


def state_to_json(state: ResearchState) -> str:
    """Serialize a validated ResearchState to JSON."""

    return _STATE_ADAPTER.dump_json(validate_state(state)).decode("utf-8")


def state_from_json(payload: str | bytes) -> ResearchState:
    """Parse and validate a ResearchState JSON payload."""

    try:
        state = _STATE_ADAPTER.validate_json(payload)
    except ValidationError as error:
        raise StateValidationError("invalid research state JSON") from error
    return validate_state(state)
