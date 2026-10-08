"""Unit tests for dependency-free evidence integrity and literal checks."""

import unittest

from paperguide.document import Page
from paperguide.verification import DeterministicEvidenceChecker, EvidenceClaim

from .verification_fixtures import make_document, make_evidence


def claim_for(document, *, claim=None, quote=None, page=1):
    evidence = make_evidence(document, page_number=page, quote=quote, claim=claim)
    return EvidenceClaim(evidence=evidence, claim=claim or evidence.normalized_fact)


class TestDeterministicEvidenceChecker(unittest.TestCase):
    def setUp(self):
        self.checker = DeterministicEvidenceChecker()

    def test_valid_quote_and_locator(self):
        document = make_document()

        result = self.checker.check(claim_for(document), document)

        self.assertTrue(result.location_valid)
        self.assertTrue(result.quote_valid)
        self.assertFalse(result.hard_reject)

    def _claim_without_offsets(self, page_text, quote, claim):
        """Evidence whose quote is not byte-identical to the parsed source.

        The reader supplies a quote; the offsets it recorded do not survive a
        source that spells the same passage differently, so the checker falls
        back to searching the text. That fallback is what these tests cover.
        """
        document = make_document()
        document = document.model_copy(
            update={
                "pages": [Page(page_number=1, text=page_text), *document.pages[1:]],
                "sections": [],
            }
        )
        evidence = make_evidence(document)
        locator = evidence.locator.model_copy(
            update={"char_start": None, "char_end": None, "section_title": None}
        )
        evidence = evidence.model_copy(update={"quote": quote, "locator": locator})
        return EvidenceClaim(evidence=evidence, claim=claim), document

    def test_typeset_ligature_and_split_word_still_match(self):
        """A reader quotes clean text; the parser emits what the PDF holds.

        Observed on a real paper: the source carried "task of<ligature>load-\nning"
        as a single ligature character with the word broken across lines, while
        the quote read "task offloading". Comparing the raw strings rejected
        evidence that was present and correctly quoted.
        """
        item, document = self._claim_without_offsets(
            "Method\nThe method reduces task of\ufb02oad-\ning delay.",
            "reduces task offloading delay",
            "The method reduces offloading delay",
        )

        result = self.checker.check(item, document)

        self.assertTrue(result.quote_valid)
        self.assertFalse(result.hard_reject)

    def test_a_compound_keeps_its_own_hyphen(self):
        """Joining every line-break hyphen would corrupt real compounds.

        "UAV-\nassisted" is one hyphenated word split by layout, not two
        syllables, so a quote saying "UAV-assisted" must still match.
        """
        item, document = self._claim_without_offsets(
            "Method\nWe study UAV-\nassisted offloading.",
            "We study UAV-assisted offloading.",
            "The paper studies UAV-assisted offloading",
        )

        result = self.checker.check(item, document)

        self.assertTrue(result.quote_valid)

    def test_unrelated_text_still_fails(self):
        """Widening the match must not make everything match."""
        item, document = self._claim_without_offsets(
            "Method\nThe method reduces task of\ufb02oad-\ning delay.",
            "quantum annealing outperforms every baseline",
            "Quantum annealing wins",
        )

        result = self.checker.check(item, document)

        self.assertFalse(result.quote_valid)
        self.assertTrue(result.hard_reject)

    def test_quote_no_longer_present_is_hard_reject(self):
        document = make_document()
        evidence_claim = claim_for(document)
        evidence = evidence_claim.evidence.model_copy(update={"quote": "fabricated"})
        evidence_claim = evidence_claim.model_copy(update={"evidence": evidence})

        result = self.checker.check(evidence_claim, document)

        self.assertTrue(result.hard_reject)

    def test_page_outside_document_is_hard_reject(self):
        document = make_document()
        item = claim_for(document)
        locator = item.evidence.locator.model_copy(
            update={"page_start": 99, "page_end": 99}
        )
        evidence = item.evidence.model_copy(update={"locator": locator})

        result = self.checker.check(item.model_copy(update={"evidence": evidence}), document)

        self.assertTrue(result.hard_reject)

    def test_paper_id_mismatch_is_hard_reject(self):
        source = make_document()
        other = make_document()

        result = self.checker.check(claim_for(source), other)

        self.assertTrue(result.hard_reject)
        self.assertFalse(result.location_valid)

    def test_claim_numbers_present_in_quote(self):
        document = make_document()
        item = claim_for(document, claim="ATE improves from 0.20 m to 0.12 m")

        result = self.checker.check(item, document)

        self.assertEqual(result.numeric_consistency.missing_numbers, [])

    def test_missing_claim_number_produces_high_warning(self):
        document = make_document()
        item = claim_for(document, claim="ATE improves to 0.05 m")

        result = self.checker.check(item, document)

        self.assertEqual(result.numeric_consistency.missing_numbers, ["0.05"])
        self.assertTrue(any("HIGH" in warning for warning in result.warnings))

    def test_units_match(self):
        document = make_document()
        item = claim_for(document, claim="ATE is 0.12 m")

        result = self.checker.check(item, document)

        self.assertTrue(result.numeric_consistency.unit_matches)

    def test_unit_conflict_is_reported(self):
        document = make_document()
        item = claim_for(document, claim="ATE is 0.12 cm")

        result = self.checker.check(item, document)

        self.assertFalse(result.numeric_consistency.unit_matches)

    def test_english_direction_matches(self):
        document = make_document()
        item = claim_for(document, claim="The method improves ATE")

        result = self.checker.check(item, document)

        self.assertTrue(result.numeric_consistency.direction_matches)

    def test_english_direction_conflict(self):
        document = make_document()
        item = claim_for(document, claim="The method reduces ATE")

        result = self.checker.check(item, document)

        self.assertFalse(result.numeric_consistency.direction_matches)

    def test_chinese_direction_terms(self):
        document = make_document()
        evidence = make_evidence(document)
        evidence = evidence.model_copy(update={"quote": "准确率提升了 5%"})
        locator = evidence.locator.model_copy(update={"char_start": None, "char_end": None})
        evidence = evidence.model_copy(update={"locator": locator})
        chinese_document = document.model_copy(
            update={"pages": [document.pages[0].model_copy(update={"text": "准确率提升了 5%"}), *document.pages[1:]], "sections": []}
        )
        item = EvidenceClaim(evidence=evidence, claim="准确率提高了 5%")

        result = self.checker.check(item, chinese_document)

        self.assertTrue(result.numeric_consistency.direction_matches)

    def test_inputs_are_not_modified(self):
        document = make_document()
        item = claim_for(document)
        document_before = document.model_dump(mode="json")
        item_before = item.model_dump(mode="json")

        self.checker.check(item, document)

        self.assertEqual(document.model_dump(mode="json"), document_before)
        self.assertEqual(item.model_dump(mode="json"), item_before)


if __name__ == "__main__":
    unittest.main()
