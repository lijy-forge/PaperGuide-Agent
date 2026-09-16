"""Unit tests for safe ResearchReport export."""

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from paperguide.domain import SourceLocator
from paperguide.export import (
    ExportFormat,
    ExportResult,
    ExportValidationError,
    HTMLExporter,
    MarkdownExporter,
    PDFExporter,
    PDFExportError,
    PyMuPDFRenderer,
)
from paperguide.reporting import (
    ReportCitation,
    ReportClaim,
    ReportSection,
    ResearchReport,
)


def make_report() -> ResearchReport:
    """Create one internally complete evidence-grounded report."""

    paper_id = uuid4()
    evidence_id = uuid4()
    locator = SourceLocator(
        paper_id=paper_id,
        section_title="Method",
        page_start=2,
        page_end=2,
        paragraph_index=1,
    )
    return ResearchReport(
        question="How does the method improve localization?",
        title="Localization Report",
        summary="The verified evidence reports an accuracy improvement.",
        sections=[
            ReportSection(
                title="Method",
                claims=[
                    ReportClaim(
                        text="The method improves localization accuracy.",
                        evidence_ids=[evidence_id],
                    )
                ],
                evidence_ids=[evidence_id],
            )
        ],
        citations=[
            ReportCitation(
                paper_id=paper_id,
                evidence_id=evidence_id,
                quote="The method improves ATE from 0.20 m to 0.12 m.",
                locator=locator,
            )
        ],
        evidence_ids=[evidence_id],
        warnings=["Limited to the reported benchmark."],
    )


class FakePDFRenderer:
    """Return deterministic PDF bytes and record supplied HTML."""

    def __init__(self, error=None, payload=b"%PDF-1.7\nfake\n%%EOF"):
        self.error = error
        self.payload = payload
        self.calls = []

    def render(self, html: str) -> bytes:
        self.calls.append(html)
        if self.error is not None:
            raise self.error
        return self.payload


class ExportTests(unittest.TestCase):
    """Verify formats, grounding checks, escaping, isolation, and failures."""

    def test_markdown_export_preserves_citations_and_warnings(self) -> None:
        report = make_report()

        result = MarkdownExporter().export(report)

        self.assertEqual(result.format, ExportFormat.MARKDOWN)
        self.assertIn("[1, p.2]", result.content)
        self.assertIn("Evidence Ledger", result.content)
        self.assertNotIn(str(report.evidence_ids[0]), result.content)
        self.assertNotIn(str(report.citations[0].paper_id), result.content)
        self.assertIn("## Scope and evidence limitations", result.content)
        self.assertIn("## Evidence Ledger", result.content)
        self.assertIn(report.warnings[0], result.content)

    def test_html_export_has_evidence_cards_and_citations(self) -> None:
        report = make_report()

        result = HTMLExporter().export(report)

        self.assertEqual(result.format, ExportFormat.HTML)
        self.assertIn('href="#reference-1"', result.content)
        self.assertIn("Evidence Ledger", result.content)
        self.assertNotIn(str(report.evidence_ids[0]), result.content)
        self.assertNotIn(str(report.citations[0].paper_id), result.content)

    def test_pdf_export_generates_file_from_html(self) -> None:
        report = make_report()
        renderer = FakePDFRenderer()
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "report.pdf"

            result = PDFExporter(renderer=renderer).export(report, output_path)

            self.assertEqual(result.format, ExportFormat.PDF)
            self.assertTrue(output_path.read_bytes().startswith(b"%PDF"))
            self.assertEqual(result.size_bytes, output_path.stat().st_size)
            self.assertIn("<!doctype html>", renderer.calls[0])

    def test_default_pdf_renderer_uses_required_pymupdf_runtime(self) -> None:
        self.assertIsInstance(PDFExporter().renderer, PyMuPDFRenderer)

    def test_pymupdf_renderer_generates_readable_pdf(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "report.pdf"

            result = PDFExporter().export(make_report(), output_path)

            self.assertEqual(result.format, ExportFormat.PDF)
            self.assertTrue(output_path.read_bytes().startswith(b"%PDF"))
            with pymupdf.open(output_path) as document:
                self.assertGreaterEqual(document.page_count, 1)
                text = "".join(page.get_text() for page in document)
            self.assertIn("Localization Report", text)

    def test_missing_evidence_is_rejected(self) -> None:
        report = make_report()
        missing = uuid4()
        report.sections[0].evidence_ids = [missing]
        report.sections[0].claims[0].evidence_ids = [missing]

        with self.assertRaises(ExportValidationError):
            MarkdownExporter().export(report)

    def test_incomplete_citation_is_rejected(self) -> None:
        report = make_report()
        report.citations = []

        with self.assertRaises(ExportValidationError):
            HTMLExporter().export(report)

    def test_empty_citation_quote_is_rejected(self) -> None:
        report = make_report()
        report.citations[0].quote = ""

        with self.assertRaises(ExportValidationError):
            HTMLExporter().export(report)

    def test_unsupported_claim_blocks_export(self) -> None:
        report = make_report()
        report.sections[0].claims.append(
            ReportClaim(text="A speculative benefit.", evidence_ids=[])
        )

        with self.assertRaises(ExportValidationError):
            MarkdownExporter().export(report)

    def test_html_escapes_untrusted_report_text(self) -> None:
        report = make_report()
        report.title = "<script>alert('title')</script>"
        report.summary = "<img src=x onerror=alert(1)>"
        report.sections[0].claims[0].text = "<b>unsafe claim</b>"
        report.citations[0].quote = "<svg onload=alert(1)>"
        report.warnings = ["<iframe src=evil></iframe>"]

        html = HTMLExporter().export(report).content

        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertNotIn("<b>unsafe claim</b>", html)
        self.assertNotIn("<svg onload", html)
        self.assertNotIn("<iframe", html)
        self.assertIn("&lt;script&gt;", html)

    def test_exporters_do_not_modify_input(self) -> None:
        report = make_report()
        original = report.model_copy(deep=True)

        MarkdownExporter().export(report)
        HTMLExporter().export(report)
        with tempfile.TemporaryDirectory() as directory:
            PDFExporter(renderer=FakePDFRenderer()).export(
                report,
                Path(directory) / "report.pdf",
            )

        self.assertEqual(report, original)

    def test_pdf_renderer_failure_is_wrapped(self) -> None:
        renderer = FakePDFRenderer(error=RuntimeError("conversion failed"))
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "report.pdf"

            with self.assertRaises(PDFExportError):
                PDFExporter(renderer=renderer).export(make_report(), output_path)

            self.assertFalse(output_path.exists())

    def test_invalid_pdf_payload_is_rejected(self) -> None:
        renderer = FakePDFRenderer(payload=b"not a pdf")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PDFExportError):
                PDFExporter(renderer=renderer).export(
                    make_report(),
                    Path(directory) / "report.pdf",
                )

    def test_nonbinary_pdf_payload_is_rejected(self) -> None:
        renderer = FakePDFRenderer(payload="not binary")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PDFExportError):
                PDFExporter(renderer=renderer).export(
                    make_report(),
                    Path(directory) / "report.pdf",
                )

    def test_export_result_json_round_trip(self) -> None:
        result = MarkdownExporter().export(make_report())

        restored = ExportResult.model_validate_json(result.model_dump_json())

        self.assertEqual(restored, result)


if __name__ == "__main__":
    unittest.main()
