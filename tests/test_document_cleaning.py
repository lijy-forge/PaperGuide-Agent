"""Unit tests for conservative deterministic document text cleaning."""

import unittest
from uuid import uuid4

from paperguide.document import (
    Document,
    DocumentCleaningConfig,
    DocumentTextCleaner,
    Page,
    Section,
)
from pydantic import ValidationError


def make_document(page_texts: list[str]) -> Document:
    return Document(
        paper_id=uuid4(),
        title="Cleaning Test",
        source_path="paper.pdf",
        pages=[
            Page(page_number=index + 1, text=text)
            for index, text in enumerate(page_texts)
        ],
        sections=[
            Section(
                title="Introduction",
                page_start=1,
                page_end=max(1, len(page_texts)),
                text="Introduction   \n\n\n\nBody   ",
            )
        ],
        metadata={"page_count": len(page_texts)},
    )


class TestDocumentTextCleaner(unittest.TestCase):
    def test_trailing_whitespace_is_removed(self):
        document = make_document(["Title   \nBody\t \n"])

        cleaned = DocumentTextCleaner().clean(document)

        self.assertEqual(cleaned.pages[0].text, "Title\nBody")

    def test_whitespace_only_lines_are_normalized(self):
        document = make_document(["Title\n   \nBody"])

        cleaned = DocumentTextCleaner().clean(document)

        self.assertEqual(cleaned.pages[0].text, "Title\n\nBody")

    def test_three_or_more_blank_lines_are_collapsed(self):
        document = make_document(["Title\n\n\n\n\nBody"])

        cleaned = DocumentTextCleaner().clean(document)

        self.assertEqual(cleaned.pages[0].text, "Title\n\n\nBody")

    def test_repeated_headers_are_removed_across_pages(self):
        document = make_document(
            [
                "PaperGuide 2026\nPage one body",
                "PaperGuide 2026\nPage two body",
                "PaperGuide 2026\nPage three body",
            ]
        )

        cleaned = DocumentTextCleaner().clean(document)

        self.assertTrue(all("PaperGuide 2026" not in page.text for page in cleaned.pages))
        self.assertIn("cleaning_warnings", cleaned.metadata)
        self.assertEqual(cleaned.sections, document.sections)

    def test_repeated_footers_are_removed_across_pages(self):
        document = make_document(
            ["Page one\nConference", "Page two\nConference", "Page three\nConference"]
        )

        cleaned = DocumentTextCleaner().clean(document)

        self.assertTrue(all("Conference" not in page.text for page in cleaned.pages))

    def test_one_or_two_repetitions_are_not_removed(self):
        document = make_document(
            ["Shared sentence\nFirst", "Shared sentence\nSecond", "Different\nThird"]
        )

        cleaned = DocumentTextCleaner().clean(document)

        self.assertEqual(cleaned.pages[0].text.splitlines()[0], "Shared sentence")
        self.assertEqual(cleaned.pages[1].text.splitlines()[0], "Shared sentence")

    def test_input_document_is_not_modified(self):
        document = make_document(["Header   \nBody"])
        before = document.model_dump(mode="json")

        cleaned = DocumentTextCleaner().clean(document)

        self.assertEqual(document.model_dump(mode="json"), before)
        self.assertIsNot(cleaned, document)

    def test_disabled_margin_and_blank_options_preserve_structure(self):
        document = make_document(
            ["Header\n\n\n\nBody", "Header\n\n\n\nOther", "Header\n\n\n\nLast"]
        )
        cleaner = DocumentTextCleaner(
            DocumentCleaningConfig(
                collapse_blank_lines=False,
                remove_repeated_headers=False,
                remove_repeated_footers=False,
            )
        )

        cleaned = cleaner.clean(document)

        self.assertEqual(cleaned.pages[0].text, document.pages[0].text)
        self.assertEqual(cleaned.sections[0].text, "Introduction\n\n\n\nBody")

    def test_cleaning_config_rejects_invalid_thresholds(self):
        with self.assertRaises(ValidationError):
            DocumentCleaningConfig(repetition_ratio=0)
        with self.assertRaises(ValidationError):
            DocumentCleaningConfig(max_header_footer_length=0)


if __name__ == "__main__":
    unittest.main()
