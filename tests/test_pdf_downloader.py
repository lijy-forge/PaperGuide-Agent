"""Unit tests for the validated PaperPilot PDF downloader."""

import socket
import tempfile
import unittest
from pathlib import Path

from paperpilot.document import (
    InvalidPDFError,
    PdfDownloader,
    PdfNetworkError,
)
from paperpilot.domain import Author, FullTextStatus, PaperCandidate, PaperSource


PDF_BYTES = b"%PDF-1.4\nmock paper content\n%%EOF"


def make_paper(pdf_url: str | None = "https://example.com/paper.pdf") -> PaperCandidate:
    return PaperCandidate(
        title="Downloaded Paper",
        normalized_title="downloaded paper",
        abstract=None,
        authors=[Author(full_name="Ada Researcher", affiliations=[])],
        publication_year=2025,
        venue=None,
        doi=None,
        arxiv_id=None,
        semantic_scholar_id=None,
        openalex_id=None,
        sources=[PaperSource.WEB],
        landing_page_url=None,
        pdf_url=pdf_url,
        citation_count=None,
        full_text_status=FullTextStatus.AVAILABLE,
        relevance_score=None,
        selection_reason=None,
    )


class MockResponse:
    """Chunk-readable context-managed response for downloader tests."""

    def __init__(
        self,
        payload: bytes,
        *,
        status: int = 200,
        content_type: str = "application/pdf",
        content_length: int | None = None,
    ):
        self.payload = payload
        self.status = status
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, size: int) -> bytes:
        chunk = self.payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class TestPdfDownloader(unittest.TestCase):
    def test_valid_pdf_is_downloaded(self):
        paper = make_paper()
        before = paper.model_dump(mode="json")
        with tempfile.TemporaryDirectory() as directory:
            downloader = PdfDownloader(
                directory,
                opener=lambda request, timeout: MockResponse(
                    PDF_BYTES,
                    content_length=len(PDF_BYTES),
                ),
            )

            downloaded = downloader.download(paper)

            self.assertEqual(downloaded.paper_id, paper.id)
            self.assertEqual(downloaded.size_bytes, len(PDF_BYTES))
            self.assertEqual(Path(downloaded.file_path).read_bytes(), PDF_BYTES)
        self.assertEqual(paper.model_dump(mode="json"), before)

    def test_http_failure_is_wrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = PdfDownloader(
                directory,
                opener=lambda request, timeout: MockResponse(
                    b"server error", status=503, content_type="text/plain"
                ),
            )

            with self.assertRaises(PdfNetworkError) as context:
                downloader.download(make_paper())

        self.assertIn("HTTP status 503", str(context.exception))

    def test_timeout_is_wrapped(self):
        def raise_timeout(request, timeout):
            raise socket.timeout("timed out")

        with tempfile.TemporaryDirectory() as directory:
            downloader = PdfDownloader(directory, opener=raise_timeout)

            with self.assertRaises(PdfNetworkError):
                downloader.download(make_paper())

    def test_non_pdf_response_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = PdfDownloader(
                directory,
                opener=lambda request, timeout: MockResponse(
                    b"<html>not a PDF</html>", content_type="text/html"
                ),
            )

            with self.assertRaises(InvalidPDFError):
                downloader.download(make_paper())

    def test_pdf_magic_header_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = PdfDownloader(
                directory,
                opener=lambda request, timeout: MockResponse(
                    b"not a PDF", content_type="application/pdf"
                ),
            )

            with self.assertRaises(InvalidPDFError):
                downloader.download(make_paper())

    def test_empty_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = PdfDownloader(
                directory,
                opener=lambda request, timeout: MockResponse(b""),
            )

            with self.assertRaises(InvalidPDFError):
                downloader.download(make_paper())

    def test_file_size_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = PdfDownloader(
                directory,
                max_size_bytes=8,
                opener=lambda request, timeout: MockResponse(
                    PDF_BYTES,
                    content_length=len(PDF_BYTES),
                ),
            )

            with self.assertRaises(InvalidPDFError):
                downloader.download(make_paper())


if __name__ == "__main__":
    unittest.main()
