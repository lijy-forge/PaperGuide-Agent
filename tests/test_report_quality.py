"""Regression tests for Q2 artifact-promotion quality semantics."""

from paperguide.application.report_quality import ReportQualityContract
from paperguide.relevance import ReportMode
from paperguide.reporting import SurveyReport


def _empty_survey() -> SurveyReport:
    return SurveyReport(
        metadata={}, query_language="en", title="Empty", abstract="Empty",
        introduction="", literature_method="", evidence_summary="", limitations="", conclusion="",
        claims=[], references=[], evidence_appendix=[], literature_timeline=[],
        report_mode=ReportMode.EVIDENCE_LIMITED_REVIEW, warnings=[], sections=[],
    )


def test_zero_evidence_zero_citation_zero_reference_is_rejected() -> None:
    decision = ReportQualityContract().assess(_empty_survey())
    assert decision.accepted is False
    assert decision.citation_registry_count == 0
    assert decision.reference_entry_count == 0
    assert decision.public_citation_count == 0
