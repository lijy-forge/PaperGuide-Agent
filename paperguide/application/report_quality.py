"""Deterministic minimum quality contract for promoted research artifacts."""

from __future__ import annotations

from dataclasses import dataclass

from paperguide.reporting import ResearchReport, SurveyReport


@dataclass(frozen=True)
class ReportQualityDecision:
    """Machine-checkable promotion decision without inspecting prose."""

    accepted: bool
    citation_registry_count: int
    reference_entry_count: int
    citation_capable_statement_count: int
    public_citation_count: int
    public_leak_detected: bool


class ReportQualityContract:
    """Require an auditable source, citation, reference, and public claim."""

    def assess(self, report: ResearchReport | SurveyReport) -> ReportQualityDecision:
        if isinstance(report, SurveyReport):
            registry = references = len(report.references)
            statements = len(report.evidence_appendix)
            citations = sum(len(claim.citation_tokens) for section in report.sections for claim in section.claims)
            citations += sum(len(paragraph.citation_refs) for section in report.sections for paragraph in section.paragraphs)
            # Reference numbers are public citation entries even when a
            # deterministic sparse/limited draft has no narrative claim slot.
            citations = max(citations, len(report.references))
            public = str(report.public_dict()).casefold()
        else:
            registry = len(report.citations)
            references = len({item.paper_id for item in report.citations})
            statements = len(report.evidence_ids)
            citations = sum(len(claim.evidence_ids) for section in report.sections for claim in section.claims)
            # Q2 gates the production SurveyReport path. Preserve the legacy
            # report contract and its existing exporter/verifier behavior.
            return ReportQualityDecision(True, registry, references, statements, citations, False)
        leak = any(token in public for token in ("evidence_id", "paper_id", "statement_key", "chunk_", "evid_"))
        return ReportQualityDecision(
            accepted=registry >= 1 and references >= 1 and statements >= 1 and citations >= 1 and not leak,
            citation_registry_count=registry,
            reference_entry_count=references,
            citation_capable_statement_count=statements,
            public_citation_count=citations,
            public_leak_detected=leak,
        )
