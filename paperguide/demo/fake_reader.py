"""Deterministic offline paper reader compatible with ReaderNode."""

from uuid import NAMESPACE_URL, uuid5

from paperguide.analysis import PaperAnalysisResult
from paperguide.document import Document
from paperguide.domain import (
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
                f"https://paperguide.local/demo/{document.paper_id}/method",
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
                f"https://paperguide.local/demo/{document.paper_id}/experiment",
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
        rich_demo = bool(metadata.get("rich_demo"))
        advantage_evidence = Evidence(
            id=uuid5(
                NAMESPACE_URL,
                f"https://paperguide.local/demo/{document.paper_id}/advantage",
            ),
            paper_id=document.paper_id,
            evidence_type=EvidenceType.DIRECT,
            quote=str(metadata["advantage"]),
            normalized_fact=str(metadata["advantage"]),
            locator=SourceLocator(
                paper_id=document.paper_id,
                section_title="Strengths and limitations",
                page_start=1,
                page_end=1,
            ),
            confidence=0.93,
        )
        limitation_evidence = Evidence(
            id=uuid5(
                NAMESPACE_URL,
                f"https://paperguide.local/demo/{document.paper_id}/limitation",
            ),
            paper_id=document.paper_id,
            evidence_type=EvidenceType.DIRECT,
            quote=str(metadata["limitation"]),
            normalized_fact=str(metadata["limitation"]),
            locator=SourceLocator(
                paper_id=document.paper_id,
                section_title="Strengths and limitations",
                page_start=1,
                page_end=1,
            ),
            confidence=0.92,
        )
        evidence = [method_evidence, experiment_evidence]
        if rich_demo:
            evidence.extend([advantage_evidence, limitation_evidence])
        return PaperAnalysisResult(
            paper_id=document.paper_id,
            document_id=document.id,
            research_problem=(
                "Improve visual SLAM robustness and semantic mapping with YOLO "
                "observations."
            ),
            contributions=[str(metadata["method_quote"])]
            + ([str(metadata["advantage"])] if rich_demo else []),
            method_summary=MethodSummary(
                paper_id=document.paper_id,
                name=str(metadata["method_name"]),
                problem=(
                    "Dynamic scenes and missing object semantics reduce SLAM "
                    "reliability."
                ),
                summary=str(metadata["method_quote"]),
                innovations=[str(metadata["method_name"])],
                limitations=[str(metadata["limitation"])],
                evidence_ids=[
                    method_evidence.id,
                    *([advantage_evidence.id, limitation_evidence.id] if rich_demo else []),
                ],
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
            evidence=evidence,
            limitations=[str(metadata["limitation"])],
            warnings=["Demo analysis was generated deterministically without an LLM."],
            confidence=0.94,
            model_name="paperguide-demo-reader",
            prompt_version="demo-v1",
        )
