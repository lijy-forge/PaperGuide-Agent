"""Regression coverage for public survey citation reconstruction."""

import re

import pymupdf
import pytest
from paperguide.reporting import (
    SurveyHtmlRenderer,
    SurveyMarkdownRenderer,
    SurveyPdfRenderer,
    SurveyPublicContentValidator,
    public_citation_refs,
)
from paperguide.reporting.exceptions import ReportSchemaValidationError

from tests.test_survey_rendering import make_report

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)


def _report_with_public_citations():
    """Create a report that mimics scope and method paragraphs from production."""

    report = make_report()
    populated = [section for section in report.sections if section.paragraphs]
    scope = populated[0]
    method = populated[1]
    scope_paragraph = scope.paragraphs[0].model_copy(
        update={
            "text": "The review scope includes one selected core study with verified evidence.",
            # These are deliberately internal and must never reach output.
            "claim_keys": [f"internal-statement-{index}" for index in range(5)],
            "citation_refs": ["[1]"],
        }
    )
    method_paragraph = method.paragraphs[0].model_copy(
        update={
            "text": "The comparison discusses two selected papers only where verified coverage exists.",
            "claim_keys": ["internal-statement-a", "internal-statement-b"],
            "citation_refs": ["[1,2]"],
        }
    )
    sections = []
    for section in report.sections:
        if section.section_id == scope.section_id:
            sections.append(scope.model_copy(update={"paragraphs": [scope_paragraph]}))
        elif section.section_id == method.section_id:
            sections.append(method.model_copy(update={"paragraphs": [method_paragraph]}))
        else:
            sections.append(section)
    return report.model_copy(update={"sections": sections})


def test_multiple_statement_keys_from_one_paper_render_as_one_public_citation():
    report = make_report()
    rows = [item for item in report.evidence_appendix if item.citation_number == 1]
    assert rows
    # Reproduce the former scope paragraph failure: five internal statement
    # keys resolving to the same paper must never become five visible IDs.
    copies = [rows[index % len(rows)].model_copy(update={"statement_key": f"internal-statement-{index}", "page": index + 1}) for index in range(5)]
    assert public_citation_refs([item.statement_key for item in copies], copies) == ["[1]"]


def test_single_verified_locator_keeps_a_public_page_citation():
    report = make_report()
    row = next(item for item in report.evidence_appendix if item.page is not None)
    assert public_citation_refs([row.statement_key], [row]) == [f"[{row.citation_number}, p.{row.page}]"]


def test_public_serialization_and_all_renderers_contain_no_internal_identifiers():
    report = make_report()
    public = report.public_dict()
    serialized = str(public)
    assert "statement_key" not in serialized
    assert "evidence_key" not in serialized
    assert "paper_id" not in serialized
    assert not _UUID.search(serialized)

    markdown = SurveyMarkdownRenderer().render(report)
    html = SurveyHtmlRenderer().render(report)
    pdf = SurveyPdfRenderer().render(report)
    document = pymupdf.open(stream=pdf, filetype="pdf")
    pdf_text = "\n".join(page.get_text() for page in document)
    document.close()
    for artifact in (markdown, html, pdf_text):
        assert "statement_key" not in artifact
        assert "evidence_key" not in artifact
        assert "paper_id" not in artifact
        assert not _UUID.search(artifact)


def test_unknown_public_citation_is_rejected_before_rendering():
    report = make_report()
    section = report.sections[0]
    paragraph = section.paragraphs[0].model_copy(update={"citation_refs": ["[999]"]})
    changed = report.model_copy(update={"sections": [section.model_copy(update={"paragraphs": [paragraph]})] + report.sections[1:]})
    with pytest.raises(ReportSchemaValidationError, match="UNKNOWN_PUBLIC_CITATION"):
        SurveyPublicContentValidator().validate(changed)


def test_source_quote_local_bibliography_is_not_a_report_citation():
    """Raw evidence excerpts retain source-local bracket references safely."""

    report = make_report()
    entry = report.evidence_appendix[0].model_copy(
        update={"quote": "A literal source excerpt may cite its own work [999]."}
    )
    changed = report.model_copy(
        update={"evidence_appendix": [entry, *report.evidence_appendix[1:]]}
    )
    SurveyPublicContentValidator().validate(changed)


def test_evidence_statement_local_bibliography_is_not_a_report_citation():
    """Evidence statements may retain the source paper's bracket references."""

    report = make_report()
    entry = report.evidence_appendix[0].model_copy(
        update={"statement_text": "The source reports this result [999]."}
    )
    changed = report.model_copy(
        update={"evidence_appendix": [entry, *report.evidence_appendix[1:]]}
    )
    SurveyPublicContentValidator().validate(changed)


def test_unknown_public_citation_in_report_narrative_remains_rejected():
    report = make_report()
    section = report.sections[0]
    paragraph = section.paragraphs[0].model_copy(
        update={"text": "This report-level claim uses an unknown citation [999]."}
    )
    changed = report.model_copy(
        update={
            "sections": [
                section.model_copy(update={"paragraphs": [paragraph]}),
                *report.sections[1:],
            ]
        }
    )
    with pytest.raises(ReportSchemaValidationError, match="UNKNOWN_PUBLIC_CITATION"):
        SurveyPublicContentValidator().validate(changed)

def test_source_quote_still_rejects_internal_uuid_leaks():
    report = make_report()
    entry = report.evidence_appendix[0].model_copy(
        update={"quote": "550e8400-e29b-41d4-a716-446655440000"}
    )
    changed = report.model_copy(
        update={"evidence_appendix": [entry, *report.evidence_appendix[1:]]}
    )
    with pytest.raises(ReportSchemaValidationError, match="PUBLIC_INTERNAL_ID_LEAK"):
        SurveyPublicContentValidator().validate(changed)


def test_public_validator_rejects_writer_uuid_in_section_paragraph():
    report = make_report()
    section = report.sections[0]
    paragraph = section.paragraphs[0].model_copy(update={"text": "leaked 550e8400-e29b-41d4-a716-446655440000"})
    changed = report.model_copy(update={"sections": [section.model_copy(update={"paragraphs": [paragraph]})] + report.sections[1:]})
    with pytest.raises(ReportSchemaValidationError, match="PUBLIC_INTERNAL_ID_LEAK"):
        SurveyPublicContentValidator().validate(changed)


@pytest.mark.parametrize(
    "token",
    [
        "allowed_statement_keys",
        "source_statement_keys",
        "method_family_counts",
        "TAXONOMY_UNAVAILABLE",
        "SLOT_ONLY",
        "chunk_12",
        "EVID_0032",
        "Stage A",
        "阶段B草稿",
    ],
)
def test_public_validator_rejects_internal_schema_tokens(token):
    report = make_report()
    section = report.sections[0]
    paragraph = section.paragraphs[0].model_copy(
        update={"text": f"Internal control value: {token}"}
    )
    changed = report.model_copy(
        update={
            "sections": [
                section.model_copy(update={"paragraphs": [paragraph]})
            ]
            + report.sections[1:]
        }
    )
    with pytest.raises(
        ReportSchemaValidationError, match="PUBLIC_INTERNAL_SCHEMA_LEAK"
    ):
        SurveyPublicContentValidator().validate(changed)


@pytest.mark.parametrize("token", [r"C:\Users\someone\report.pdf", "/tmp/report.pdf"])
def test_public_validator_rejects_local_paths(token):
    report = make_report()
    section = report.sections[0]
    paragraph = section.paragraphs[0].model_copy(update={"text": token})
    changed = report.model_copy(
        update={"sections": [section.model_copy(update={"paragraphs": [paragraph]})] + report.sections[1:]}
    )
    with pytest.raises(ReportSchemaValidationError, match="PUBLIC_INTERNAL_ID_LEAK"):
        SurveyPublicContentValidator().validate(changed)


def test_references_remain_normal_public_citations():
    report = make_report()
    markdown = SurveyMarkdownRenderer().render(report)
    for reference in report.references:
        assert f"[{reference.citation_number}]" in markdown
        assert reference.title in markdown


def test_multiple_papers_use_one_grouped_paragraph_citation_across_formats():
    report = _report_with_public_citations()
    markdown = SurveyMarkdownRenderer().render(report)
    html = SurveyHtmlRenderer().render(report)
    document = pymupdf.open(stream=SurveyPdfRenderer().render(report), filetype="pdf")
    pdf_text = "\n".join(page.get_text() for page in document)
    links = [link for page in document for link in page.get_links()]
    document.close()
    for artifact in (markdown, html, pdf_text):
        assert "[1]" in artifact
        assert "[1,2]" in artifact
        assert "[1][1]" not in artifact
        assert "[1][2]" not in artifact
    assert "href=\"#reference-1\"" not in html  # Citations are public text, not internal links.
    # Timeline and reference source URLs are intentionally clickable, but they
    # must remain ordinary external HTTPS links rather than internal IDs.
    addressed = [link for link in links if link.get("uri")]
    assert addressed
    assert all(link["kind"] == pymupdf.LINK_URI and link["uri"].startswith("https://") for link in addressed)
    # Table-of-contents entries navigate by page number, so they carry no address to leak.
    assert all(not link.get("uri") for link in links if link["kind"] != pymupdf.LINK_URI)
