"""Unit tests for conservative Paper Reader evidence mapping."""

import unittest
from uuid import uuid4

from paperguide.analysis import EvidenceMapper, EvidenceReference
from paperguide.document import Document, Page, Section
from paperguide.domain import EvidenceType


def make_document() -> Document:
    pages = [
        Page(page_number=1, text="Abstract\nWe study robust localization."),
        Page(
            page_number=2,
            text="Method\nThe method filters dynamic\nfeatures before mapping.",
        ),
        Page(
            page_number=3,
            text="Experiments\nKITTI ATE is 0.12 m versus 0.20 m baseline.",
        ),
    ]
    return Document(
        paper_id=uuid4(),
        title="Evidence Test",
        source_path="paper.pdf",
        pages=pages,
        sections=[
            Section(title="Abstract", page_start=1, page_end=1, text=pages[0].text),
            Section(title="2 Method", page_start=2, page_end=2, text=pages[1].text),
            Section(
                title="3 Experiments", page_start=3, page_end=3, text=pages[2].text
            ),
        ],
        metadata={"page_count": 3},
    )


def reference(
    *,
    key: str = "E1",
    quote: str = "The method filters dynamic features before mapping.",
    page: int | None = 2,
    section: str | None = "Method",
) -> EvidenceReference:
    return EvidenceReference(
        evidence_key=key,
        quote=quote,
        page_number=page,
        section_title=section,
        claim="The method filters dynamic features before mapping.",
        confidence=0.9,
    )


class TestEvidenceMapper(unittest.TestCase):
    def test_quote_on_declared_page_maps_successfully(self):
        result = EvidenceMapper().map([reference()], make_document())

        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.evidence[0].evidence_type, EvidenceType.DIRECT)

    def test_source_locator_contains_declared_page(self):
        result = EvidenceMapper().map([reference()], make_document())
        locator = result.evidence[0].locator

        self.assertEqual(locator.page_start, 2)
        self.assertEqual(locator.page_end, 2)
        self.assertEqual(locator.section_title, "2 Method")

    def test_character_offsets_reference_original_page_text(self):
        document = make_document()
        result = EvidenceMapper().map([reference()], document)
        evidence = result.evidence[0]

        located = document.pages[1].text[
            evidence.locator.char_start : evidence.locator.char_end
        ]
        self.assertEqual(located, evidence.quote)
        self.assertIn("dynamic\nfeatures", located)

    def test_conservative_whitespace_differences_are_accepted(self):
        result = EvidenceMapper().map(
            [reference(quote="The method   filters dynamic features before mapping.")],
            make_document(),
        )

        self.assertEqual(len(result.evidence), 1)

    def test_nonexistent_quote_is_rejected(self):
        result = EvidenceMapper().map(
            [reference(quote="A fabricated method statement.")], make_document()
        )

        self.assertEqual(result.evidence, [])
        self.assertEqual(result.rejected_keys, ["E1"])
        self.assertIn("not found", result.warnings[0])

    def test_page_outside_document_is_rejected(self):
        result = EvidenceMapper().map([reference(page=99)], make_document())

        self.assertEqual(result.evidence, [])
        self.assertIn("outside", result.warnings[0])

    def test_unknown_section_is_rejected(self):
        result = EvidenceMapper().map(
            [reference(section="Ablation Study")], make_document()
        )

        self.assertEqual(result.rejected_keys, ["E1"])
        self.assertIn("unknown section", result.warnings[0])

    def test_page_outside_declared_section_is_rejected(self):
        result = EvidenceMapper().map(
            [
                reference(
                    quote="KITTI ATE is 0.12 m versus 0.20 m baseline.",
                    page=3,
                    section="Method",
                )
            ],
            make_document(),
        )

        self.assertEqual(result.evidence, [])
        self.assertIn("outside its declared section", result.warnings[0])

    def test_duplicate_evidence_keys_are_all_rejected(self):
        result = EvidenceMapper().map(
            [reference(), reference(quote="filters dynamic features")],
            make_document(),
        )

        self.assertEqual(result.evidence, [])
        self.assertEqual(result.rejected_keys, ["E1"])
        self.assertEqual(len(result.warnings), 1)

    def test_key_maps_to_generated_evidence_uuid(self):
        result = EvidenceMapper().map([reference()], make_document())

        self.assertEqual(result.key_to_id["E1"], result.evidence[0].id)

    def test_missing_location_searches_pages_in_stable_order(self):
        result = EvidenceMapper().map(
            [
                reference(
                    quote="We study robust localization.", page=None, section=None
                )
            ],
            make_document(),
        )

        self.assertEqual(result.evidence[0].locator.page_start, 1)

    def test_mapper_does_not_modify_document(self):
        document = make_document()
        before = document.model_dump(mode="json")

        EvidenceMapper().map([reference()], document)

        self.assertEqual(document.model_dump(mode="json"), before)


if __name__ == "__main__":
    unittest.main()
