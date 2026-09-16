"""Unit tests for unified, atomic, checksummed report export."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from paperguide.domain import SourceLocator
from paperguide.export import (
    ArtifactFormatIntegrityError,
    ArtifactFormatIntegrityValidator,
    ArtifactMetadata,
    ExportArtifactExistsError,
    ExportFormat,
    ExportPathTraversalError,
    ExportService,
    HTMLExporter,
    InvalidExportFilenameError,
    MarkdownExporter,
    PDFExporter,
)
from paperguide.reporting import (
    ReportCitation,
    ReportClaim,
    ReportSection,
    ResearchReport,
)


def make_report(title: str = "Localization Report") -> ResearchReport:
    """Create an internally complete report for service tests."""

    paper_id = uuid4()
    evidence_id = uuid4()
    locator = SourceLocator(
        paper_id=paper_id,
        section_title="Method",
        page_start=1,
        page_end=1,
    )
    return ResearchReport(
        question="How does the method improve localization?",
        title=title,
        summary="Verified evidence reports an accuracy improvement.",
        sections=[
            ReportSection(
                title="Method",
                claims=[
                    ReportClaim(
                        text="The method improves accuracy.",
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
        warnings=["Limited benchmark coverage."],
    )


class FakePDFRenderer:
    """Convert HTML into deterministic PDF-like bytes without external tools."""

    def render(self, html: str) -> bytes:
        return b"%PDF-1.7\n" + hashlib.sha256(html.encode("utf-8")).digest()


def make_service(directory: str | Path, *, overwrite: bool = False) -> ExportService:
    """Create a service with all exporters and a fake local PDF renderer."""

    return ExportService(
        directory,
        markdown_exporter=MarkdownExporter(),
        html_exporter=HTMLExporter(),
        pdf_exporter=PDFExporter(renderer=FakePDFRenderer()),
        overwrite=overwrite,
    )


class ExportServiceTests(unittest.TestCase):
    """Verify dispatch, path controls, atomic publishing, and artifact metadata."""

    def test_markdown_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = make_service(directory).export(
                make_report(),
                ExportFormat.MARKDOWN,
            )

            self.assertEqual(result.format, ExportFormat.MARKDOWN)
            self.assertTrue(Path(result.file_path).is_file())
            self.assertEqual(Path(result.file_path).suffix, ".md")
            self.assertIsNotNone(result.content)
            self.assertIsInstance(result.artifact, ArtifactMetadata)

    def test_html_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = make_service(directory).export(
                make_report(),
                ExportFormat.HTML,
                filename="research.html",
            )

            self.assertEqual(result.format, ExportFormat.HTML)
            self.assertIn("<!doctype html>", result.content)
            self.assertEqual(Path(result.file_path).name, "research.html")

    def test_pdf_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = make_service(directory).export(
                make_report(),
                ExportFormat.PDF,
                filename="research.pdf",
            )

            self.assertEqual(result.format, ExportFormat.PDF)
            self.assertIsNone(result.content)
            self.assertTrue(Path(result.file_path).read_bytes().startswith(b"%PDF"))

    def test_invalid_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(InvalidExportFilenameError):
                make_service(directory).export(
                    make_report(),
                    ExportFormat.MARKDOWN,
                    filename="invalid?.md",
                )

    def test_empty_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(InvalidExportFilenameError):
                make_service(directory).export(
                    make_report(),
                    ExportFormat.MARKDOWN,
                    filename="",
                )

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory) / "exports"
            with self.assertRaises(ExportPathTraversalError):
                make_service(output_directory).export(
                    make_report(),
                    ExportFormat.HTML,
                    filename="../escaped.html",
                )
            self.assertFalse((Path(directory) / "escaped.html").exists())

    def test_existing_file_requires_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = make_service(directory)
            first = service.export(
                make_report(),
                ExportFormat.MARKDOWN,
                filename="report.md",
            )

            with self.assertRaises(ExportArtifactExistsError):
                service.export(
                    make_report(),
                    ExportFormat.MARKDOWN,
                    filename="report.md",
                )

            self.assertEqual(
                Path(first.file_path).read_text(encoding="utf-8"),
                first.content,
            )

    def test_explicit_overwrite_replaces_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = make_service(directory)
            first_report = make_report()
            first = service.export(
                first_report,
                ExportFormat.HTML,
                filename="report.html",
            )
            second_report = first_report.model_copy(
                update={"summary": "A revised verified summary."},
                deep=True,
            )

            second = service.export(
                second_report,
                ExportFormat.HTML,
                filename="report.html",
                overwrite=True,
            )

            self.assertNotEqual(first.artifact.sha256, second.artifact.sha256)
            self.assertIn("A revised verified summary.", second.content)

    def test_sha256_matches_published_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = make_service(directory).export(
                make_report(),
                ExportFormat.PDF,
            )
            payload = Path(result.file_path).read_bytes()

            self.assertEqual(
                result.artifact.sha256,
                hashlib.sha256(payload).hexdigest(),
            )
            self.assertEqual(result.artifact.size_bytes, len(payload))
            self.assertEqual(result.size_bytes, len(payload))

    def test_input_report_is_not_modified(self) -> None:
        report = make_report()
        original = report.model_copy(deep=True)
        with tempfile.TemporaryDirectory() as directory:
            service = make_service(directory)

            service.export(report, ExportFormat.MARKDOWN)

        self.assertEqual(report, original)

    def test_atomic_temporary_files_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = make_service(directory)

            service.export(make_report(), ExportFormat.HTML)

            leftovers = list(Path(directory).glob(".paperguide-*"))
            self.assertEqual(leftovers, [])

    def test_format_integrity_rejects_extension_mime_and_magic_mismatch(self) -> None:
        validator = ArtifactFormatIntegrityValidator()
        cases = (
            (ExportFormat.PDF, "report.md", "application/pdf", b"%PDF-1.7\n"),
            (ExportFormat.PDF, "report.pdf", "text/markdown", b"%PDF-1.7\n"),
            (ExportFormat.PDF, "report.pdf", "application/pdf", b"# markdown"),
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(
                ArtifactFormatIntegrityError
            ):
                validator.validate(*case)

    def test_format_integrity_accepts_all_three_real_formats(self) -> None:
        validator = ArtifactFormatIntegrityValidator()
        validator.validate(
            ExportFormat.MARKDOWN, "report.md", "text/markdown", b"# Report"
        )
        validator.validate(
            ExportFormat.HTML,
            "report.html",
            "text/html; charset=utf-8",
            b"<!doctype html><html></html>",
        )
        validator.validate(
            ExportFormat.PDF, "report.pdf", "application/pdf", b"%PDF-1.7\n"
        )


if __name__ == "__main__":
    unittest.main()
