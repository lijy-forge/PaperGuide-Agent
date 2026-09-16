"""Unit tests for PyMuPDF-backed parsing using a compatible mock module."""

import tempfile
import unittest
from pathlib import Path

from paperguide.document import PdfParseError, PdfParser
from paperguide.domain import Author, FullTextStatus, PaperCandidate, PaperSource


def make_paper() -> PaperCandidate:
    return PaperCandidate(
        title="Parsed Paper",
        normalized_title="parsed paper",
        abstract=None,
        authors=[Author(full_name="Ada Researcher", affiliations=[])],
        publication_year=2025,
        venue=None,
        doi=None,
        arxiv_id=None,
        semantic_scholar_id=None,
        openalex_id=None,
        sources=[PaperSource.USER_UPLOAD],
        landing_page_url=None,
        pdf_url=None,
        citation_count=None,
        full_text_status=FullTextStatus.AVAILABLE,
        relevance_score=None,
        selection_reason=None,
    )


class FakePage:
    """Minimal page exposing the PyMuPDF text API."""

    def __init__(self, text: str):
        self.text = text

    def get_text(self, output_type: str) -> str:
        if output_type != "text":
            raise ValueError("unsupported output type")
        return self.text


class FakeDocument:
    """Context-managed iterable compatible with a PyMuPDF document."""

    def __init__(self, page_texts: list[str]):
        self.pages = [FakePage(text) for text in page_texts]
        self.metadata = {"author": "PaperGuide Test", "title": "Parsed Paper"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def __iter__(self):
        return iter(self.pages)


class FakePyMuPDF:
    """Mock PyMuPDF module returning a predefined multi-page document."""

    def __init__(self, page_texts: list[str]):
        self.page_texts = page_texts

    def open(self, path: str) -> FakeDocument:
        return FakeDocument(self.page_texts)


class FailingPyMuPDF:
    """Mock PyMuPDF module that rejects an invalid PDF."""

    def open(self, path: str):
        raise RuntimeError("cannot open broken document")


class TestPdfParser(unittest.TestCase):
    def setUp(self):
        self.page_texts = [
            "1 Introduction\nThis paper introduces the problem.\n",
            "RELATED WORK\nPrior systems are reviewed here.\n"
            "3 Method\nOur method combines detection and mapping.\n",
            "4 Experiments\nEvaluation uses the KITTI dataset.\n"
            "Conclusion\nThe method improves robustness.\n",
        ]

    def _parse(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        pdf_path = Path(temporary_directory.name) / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-mocked")
        parser = PdfParser(FakePyMuPDF(self.page_texts))
        paper = make_paper()
        return parser.parse(pdf_path, paper), paper

    def test_multi_page_pdf_is_parsed(self):
        document, _ = self._parse()

        self.assertEqual(len(document.pages), 3)
        self.assertEqual(document.metadata["page_count"], 3)
        self.assertEqual([page.page_number for page in document.pages], [1, 2, 3])

    def test_page_text_is_preserved(self):
        document, paper = self._parse()

        self.assertEqual(
            document.pages[1].text,
            self.page_texts[1].strip(),
        )
        self.assertEqual(document.paper_id, paper.id)

    def test_sections_are_detected(self):
        paper = make_paper()
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        pdf_path = Path(temporary_directory.name) / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-mocked")

        document = PdfParser(FakePyMuPDF(self.page_texts)).parse(pdf_path, paper)

        self.assertEqual(
            [section.title for section in document.sections],
            ["1 Introduction", "RELATED WORK", "3 Method", "4 Experiments", "Conclusion"],
        )
        introduction = document.sections[0]
        method = next(section for section in document.sections if section.title == "3 Method")
        self.assertEqual(introduction.page_start, 1)
        self.assertEqual(method.page_start, 2)
        self.assertIn("combines detection and mapping", method.text)

    def test_invalid_pdf_raises_parse_error(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "broken.pdf"
            pdf_path.write_bytes(b"not a PDF")
            parser = PdfParser(FailingPyMuPDF())

            with self.assertRaises(PdfParseError) as context:
                parser.parse(pdf_path, make_paper())

        self.assertIn("cannot open broken document", str(context.exception))


if __name__ == "__main__":
    unittest.main()
