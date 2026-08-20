"""Deterministic offline paper reader compatible with ReaderNode."""

from uuid import NAMESPACE_URL, uuid5

from paperpilot.analysis import PaperAnalysisResult
from paperpilot.document import Document
from paperpilot.domain import (
    Evidence,
    EvidenceType,
    ExperimentSummary,
    MethodSummary,
    SourceLocator,
)


class FakeReader:
    """Produce structured analyses from copyright-safe seeded document metadata."""

    def analyze(self, document: Document) -> PaperAnalysisResult:
        """Return an evidence-linked analysis without an LLM invocation."""

        metadata = document.metadata
        method_evidence = Evidence(
            id=uuid5(
                NAMESPACE_URL,
                f"https://paperpilot.local/demo/{document.paper_id}/method",
            ),
            paper_id=document.paper_id,
            evidence_type=EvidenceType.DIRECT,
            quote=str(metadata["method_quote"]),
            normalized_fact=str(metadata["method_quote"]),
            locator=SourceLocator(
                paper_id=document.paper_id,
                section_title="Method",
                page_start=1,
                page_end=1,
            ),
            confidence=0.96,
        )
        experiment_evidence = Evidence(
            id=uuid5(
                NAMESPACE_URL,
                f"https://paperpilot.local/demo/{document.paper_id}/experiment",
            ),
            paper_id=document.paper_id,
            evidence_type=EvidenceType.DIRECT,
            quote=str(metadata["experiment_quote"]),
            normalized_fact=str(metadata["experiment_quote"]),
            locator=SourceLocator(
                paper_id=document.paper_id,
                section_title="Experiments",
                page_start=1,
                page_end=1,
            ),
            confidence=0.94,
        )
        return PaperAnalysisResult(
            paper_id=document.paper_id,
            document_id=document.id,
            research_problem=(
                "Improve visual SLAM robustness and semantic mapping with YOLO "
                "observations."
            ),
            contributions=[str(metadata["method_quote"])],
            method_summary=MethodSummary(
                paper_id=document.paper_id,
                name=str(metadata["method_name"]),
                problem=(
                    "Dynamic scenes and missing object semantics reduce SLAM "
                    "reliability."
                ),
                summary=str(metadata["method_quote"]),
                innovations=[str(metadata["method_name"])],
                limitations=[
                    "Evidence is synthetic and intended only for product demonstration."
                ],
                evidence_ids=[method_evidence.id],
                confidence=0.95,
            ),
            experiment_summary=ExperimentSummary(
                paper_id=document.paper_id,
                datasets=[str(metadata["dataset"])],
                metrics={str(metadata["metric"]): str(metadata["metric_value"])},
                baselines=[str(metadata["baseline"])],
                findings=[str(metadata["experiment_quote"])],
                evidence_ids=[experiment_evidence.id],
                confidence=0.93,
            ),
            evidence=[method_evidence, experiment_evidence],
            limitations=[
                "Synthetic offline data must not be treated as academic findings."
            ],
            warnings=["Demo analysis was generated deterministically without an LLM."],
            confidence=0.94,
            model_name="paperpilot-demo-reader",
            prompt_version="demo-v1",
        )
