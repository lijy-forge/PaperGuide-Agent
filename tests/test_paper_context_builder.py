"""Unit tests for bounded and location-marked Paper Reader context."""

import unittest
from uuid import uuid4

from paperguide.analysis import (
    PaperContextBuilder,
    PaperContextConfig,
    PaperContextError,
)
from paperguide.document import Document, Page, Section
from pydantic import ValidationError


def make_document(*, with_sections: bool = True, long_method: bool = False) -> Document:
    pages = [
        Page(page_number=1, text="Abstract\nWe study robust localization in traffic."),
        Page(
            page_number=2,
            text="Method\nThe method filters dynamic features before mapping."
            + (" Fusion details." * 40 if long_method else ""),
        ),
        Page(
            page_number=3,
            text="Experiments\nKITTI ATE is 0.12 m versus 0.20 m baseline.",
        ),
        Page(page_number=4, text="Conclusion\nThe system improves robustness."),
    ]
    sections = []
    if with_sections:
        sections = [
            Section(title="Abstract", page_start=1, page_end=1, text=pages[0].text),
            Section(title="2 Method", page_start=2, page_end=2, text=pages[1].text),
            Section(
                title="3 Experiments", page_start=3, page_end=3, text=pages[2].text
            ),
            Section(title="Conclusion", page_start=4, page_end=4, text=pages[3].text),
        ]
    return Document(
        paper_id=uuid4(),
        title="Reader Test Paper",
        source_path="paper.pdf",
        pages=pages,
        sections=sections,
        metadata={"page_count": 4},
    )


class TestPaperContextBuilder(unittest.TestCase):
    def test_preferred_method_and_experiment_sections_are_selected(self):
        builder = PaperContextBuilder(
            PaperContextConfig(
                max_pages=2,
                preferred_sections=("method", "experiment"),
            )
        )

        context = builder.build(make_document())

        self.assertEqual(context.selected_sections, ["2 Method", "3 Experiments"])

    def test_missing_sections_falls_back_to_pages(self):
        context = PaperContextBuilder(
            PaperContextConfig(max_pages=2)
        ).build(make_document(with_sections=False))

        self.assertEqual(context.selected_sections, [])
        self.assertEqual(context.page_ranges, [(1, 1), (2, 2)])
        self.assertIn("fell back", context.warnings[0])

    def test_context_contains_page_and_section_markers(self):
        context = PaperContextBuilder().build(make_document())

        self.assertIn("[PAGE 2][SECTION 2 Method]", context.context_text)
        self.assertIn("[PAGE 3][SECTION 3 Experiments]", context.context_text)

    def test_numbered_section_matching_ignores_case(self):
        document = make_document()
        sections = list(document.sections)
        sections[1] = sections[1].model_copy(update={"title": "II. METHODOLOGY"})
        document = document.model_copy(update={"sections": sections})

        context = PaperContextBuilder().build(document)

        self.assertIn("II. METHODOLOGY", context.selected_sections)

    def test_long_context_is_stably_truncated(self):
        document = make_document(long_method=True)
        builder = PaperContextBuilder(
            PaperContextConfig(max_characters=180, preferred_sections=("method",))
        )

        first = builder.build(document)
        second = builder.build(document)

        self.assertEqual(first.context_text, second.context_text)
        self.assertEqual(len(first.context_text), 180)
        self.assertTrue(first.truncated)

    def test_page_limit_marks_context_truncated(self):
        context = PaperContextBuilder(
            PaperContextConfig(max_pages=2)
        ).build(make_document(with_sections=False))

        self.assertTrue(context.truncated)
        self.assertIn("max_pages", " ".join(context.warnings))

    def test_empty_document_is_rejected(self):
        document = Document(
            paper_id=uuid4(),
            title="Empty",
            source_path="empty.pdf",
            pages=[],
            sections=[],
            metadata={},
        )

        with self.assertRaises(PaperContextError):
            PaperContextBuilder().build(document)

    def test_document_is_not_modified(self):
        document = make_document()
        before = document.model_dump(mode="json")

        PaperContextBuilder().build(document)

        self.assertEqual(document.model_dump(mode="json"), before)

    def test_token_estimate_uses_character_heuristic(self):
        context = PaperContextBuilder().build(make_document())

        self.assertEqual(context.token_estimate, (len(context.context_text) + 3) // 4)

    def test_invalid_context_config_is_rejected(self):
        with self.assertRaises(ValidationError):
            PaperContextConfig(max_pages=0)
        with self.assertRaises(ValidationError):
            PaperContextConfig(max_characters=20)


if __name__ == "__main__":
    unittest.main()
