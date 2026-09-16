"""Reusable in-memory fixtures for evidence-verification unit tests."""

from uuid import uuid4

from paperguide.analysis import PaperAnalysisResult
from paperguide.document import Document, Page, Section
from paperguide.domain import (
    Evidence,
    EvidenceType,
    ExperimentSummary,
    MethodSummary,
    SourceLocator,
)
from paperguide.verification import (
    EvidenceVerificationDecision,
    SupportLevel,
    VerificationStatus,
)


def make_document() -> Document:
    method = "Method\nThe method improves ATE from 0.20 m to 0.12 m."
    experiment = "Experiments\nKITTI ATE is 0.12 m versus 0.20 m baseline."
    return Document(
        paper_id=uuid4(),
        title="Verification Paper",
        source_path="paper.pdf",
        pages=[Page(page_number=1, text=method), Page(page_number=2, text=experiment)],
        sections=[
            Section(title="Method", page_start=1, page_end=1, text=method),
            Section(title="Experiments", page_start=2, page_end=2, text=experiment),
        ],
        metadata={"page_count": 2},
    )


def make_evidence(
    document: Document,
    *,
    page_number: int = 1,
    quote: str | None = None,
    claim: str | None = None,
) -> Evidence:
    page = next(item for item in document.pages if item.page_number == page_number)
    actual_quote = quote or page.text.split("\n", 1)[1]
    start = page.text.find(actual_quote)
    return Evidence(
        paper_id=document.paper_id,
        evidence_type=EvidenceType.DIRECT,
        quote=actual_quote,
        normalized_fact=claim or actual_quote,
        locator=SourceLocator(
            paper_id=document.paper_id,
            section_title="Method" if page_number == 1 else "Experiments",
            page_start=page_number,
            page_end=page_number,
            char_start=start,
            char_end=start + len(actual_quote),
        ),
        confidence=0.9,
    )


def make_analysis(document: Document | None = None) -> tuple[PaperAnalysisResult, Document]:
    document = document or make_document()
    method_evidence = make_evidence(document, page_number=1)
    experiment_evidence = make_evidence(document, page_number=2)
    analysis = PaperAnalysisResult(
        paper_id=document.paper_id,
        document_id=document.id,
        paper_title=document.title,
        research_problem="Improve localization accuracy.",
        contributions=["A filtering method."],
        method_summary=MethodSummary(
            paper_id=document.paper_id,
            name="VerifierNet",
            problem="Localization error",
            summary="The method improves ATE from 0.20 m to 0.12 m.",
            innovations=[],
            limitations=["Limited evaluation"],
            evidence_ids=[method_evidence.id],
            confidence=0.9,
        ),
        experiment_summary=ExperimentSummary(
            paper_id=document.paper_id,
            datasets=["KITTI"],
            metrics={"KITTI:ATE": "0.12 m"},
            baselines=["0.20 m baseline"],
            findings=[],
            evidence_ids=[experiment_evidence.id],
            confidence=0.9,
        ),
        evidence=[method_evidence, experiment_evidence],
        limitations=["Limited evaluation"],
        warnings=[],
        confidence=0.9,
        model_name="reader-model",
        prompt_version="v1",
    )
    return analysis, document


def make_decision(
    evidence_id,
    claim: str,
    *,
    support: SupportLevel = SupportLevel.DIRECT,
    status: VerificationStatus = VerificationStatus.VERIFIED,
    entailment: float = 1.0,
    contradiction: float = 0.0,
    overclaim: bool = False,
) -> EvidenceVerificationDecision:
    return EvidenceVerificationDecision(
        evidence_id=evidence_id,
        claim=claim,
        support_level=support,
        status=status,
        entailment_score=entailment,
        contradiction_score=contradiction,
        overclaim_detected=overclaim,
        reasoning="The supplied quote directly supports the claim.",
        corrected_claim=None,
        warnings=[],
    )
