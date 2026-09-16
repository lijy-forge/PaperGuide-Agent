"""Local HTML-to-PDF export with an injectable rendering backend."""

from io import BytesIO
from pathlib import Path
from typing import Protocol, runtime_checkable

from paperguide.reporting import ResearchReport

from .exceptions import PDFExportError
from .html import HTMLExporter
from .models import ExportFormat, ExportResult
from .verifier import ExportVerifier


@runtime_checkable
class PDFRendererProtocol(Protocol):
    """Convert one self-contained HTML string into PDF bytes."""

    def render(self, html: str) -> bytes:
        """Return a complete PDF document."""

        ...


class WeasyPrintRenderer:
    """Render self-contained HTML through the optional local WeasyPrint package."""

    def render(self, html: str) -> bytes:
        try:
            from weasyprint import HTML
        except ImportError as error:
            raise PDFExportError(
                "PDF export requires the optional local WeasyPrint dependency"
            ) from error
        return HTML(string=html).write_pdf()


class PyMuPDFRenderer:
    """Render self-contained HTML with the project's required PyMuPDF runtime."""

    PAGE_MARGIN_POINTS = 45

    def render(self, html: str) -> bytes:
        try:
            import pymupdf
        except ImportError as error:
            raise PDFExportError(
                "PDF export requires the configured PyMuPDF dependency"
            ) from error

        buffer = BytesIO()
        writer = None
        try:
            media_box = pymupdf.paper_rect("a4")
            margin = self.PAGE_MARGIN_POINTS
            content_box = pymupdf.Rect(
                media_box.x0 + margin,
                media_box.y0 + margin,
                media_box.x1 - margin,
                media_box.y1 - margin,
            )
            story = pymupdf.Story(
                html,
                user_css=(
                    "body { font-family: sans-serif; line-height: 1.5; } "
                    "pre, code { font-family: monospace; }"
                ),
            )
            writer = pymupdf.DocumentWriter(buffer)
            story.write(
                writer,
                lambda _page_number, _filled: (
                    media_box,
                    content_box,
                    None,
                ),
            )
            writer.close()
            writer = None
        except Exception as error:
            raise PDFExportError("PyMuPDF HTML-to-PDF rendering failed") from error
        finally:
            if writer is not None:
                try:
                    writer.close()
                except Exception:
                    pass
        return buffer.getvalue()


class PDFExporter:
    """Verify a report, render safe HTML, and write a local PDF file."""

    def __init__(
        self,
        renderer: PDFRendererProtocol | None = None,
        verifier: ExportVerifier | None = None,
    ) -> None:
        self.verifier = verifier or ExportVerifier()
        # PyMuPDF is already required by the document parser and works on all
        # supported platforms. WeasyPrint requires external GTK/Pango libraries
        # on Windows and therefore cannot be the safe production default.
        self.renderer = renderer or PyMuPDFRenderer()
        self.html_exporter = HTMLExporter(self.verifier)

    def export(
        self,
        report: ResearchReport,
        output_path: str | Path,
    ) -> ExportResult:
        """Generate a PDF file or raise a typed error without partial recovery."""

        html = self.html_exporter.render(report)
        try:
            pdf_bytes = self.renderer.render(html)
        except PDFExportError:
            raise
        except Exception as error:
            raise PDFExportError("HTML-to-PDF rendering failed") from error
        if not isinstance(pdf_bytes, (bytes, bytearray)):
            raise PDFExportError("HTML-to-PDF renderer returned non-binary content")
        pdf_payload = bytes(pdf_bytes)
        if not pdf_payload or not pdf_payload.startswith(b"%PDF"):
            raise PDFExportError("HTML-to-PDF renderer returned an invalid PDF")

        path = Path(output_path)
        try:
            path.write_bytes(pdf_payload)
        except OSError as error:
            raise PDFExportError(f"could not write PDF file {path}") from error
        return ExportResult(
            format=ExportFormat.PDF,
            media_type="application/pdf",
            content=None,
            file_path=str(path.resolve()),
            size_bytes=len(pdf_payload),
            warnings=list(report.warnings),
        )
