"""Unit tests for PaperGuide document-layer Pydantic models."""

import unittest
from uuid import uuid4

from paperguide.document import Document, Page, Section
from pydantic import ValidationError


class TestDocumentModels(unittest.TestCase):
    def test_page_can_be_created(self):
        page = Page(page_number=1, text="Introduction text")

        self.assertEqual(page.page_number, 1)
        self.assertEqual(page.text, "Introduction text")

    def test_page_number_must_be_positive(self):
        with self.assertRaises(ValidationError):
            Page(page_number=0, text="Invalid page")

    def test_section_can_be_created(self):
        section = Section(
            title="1 Introduction",
            page_start=1,
            page_end=2,
            text="1 Introduction\nSection body",
        )

        self.assertEqual(section.page_start, 1)
        self.assertEqual(section.page_end, 2)

    def test_section_rejects_reversed_page_range(self):
        with self.assertRaises(ValidationError):
            Section(title="Method", page_start=3, page_end=2, text="Body")

    def test_document_json_round_trip(self):
        document = Document(
            paper_id=uuid4(),
            title="A Paper",
            source_path="/tmp/paper.pdf",
            pages=[Page(page_number=1, text="Introduction")],
            sections=[
                Section(
                    title="Introduction",
                    page_start=1,
                    page_end=1,
                    text="Introduction",
                )
            ],
            metadata={"page_count": 1, "parser": "pymupdf"},
        )

        restored = Document.model_validate_json(document.model_dump_json())

        self.assertEqual(restored, document)

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            Page(page_number=1, text="Text", unknown="value")


if __name__ == "__main__":
    unittest.main()
