"""Tests for re-locating evidence a deterministic check could not find.

A relocator may only say where to look again. These cover what it recovers,
what it must refuse, and that nothing it returns can weaken the check that
follows it.
"""

import unittest
from uuid import uuid4

from paperguide.document import Page
from paperguide.verification import (
    DeterministicEvidenceChecker,
    EvidenceClaim,
    EvidenceVerifier,
)
from paperguide.verification.relocation import (
    EvidenceRelocation,
    FuzzyEvidenceRelocator,
)

from .verification_fixtures import make_document, make_evidence


def claim_on_page(document, quote, page_number):
    """A claim whose recorded coordinates no longer locate its quote."""
    evidence = make_evidence(document)
    locator = evidence.locator.model_copy(
        update={
            "page_start": page_number,
            "page_end": page_number,
            "section_title": None,
            "char_start": None,
            "char_end": None,
        }
    )
    evidence = evidence.model_copy(update={"quote": quote, "locator": locator})
    return EvidenceClaim(evidence=evidence, claim="a claim about the quote")


class TestFuzzyEvidenceRelocator(unittest.TestCase):
    def setUp(self):
        self.checker = DeterministicEvidenceChecker()
        self.relocator = FuzzyEvidenceRelocator()

    def test_finds_a_quote_recorded_on_the_wrong_page(self):
        document = make_document()
        quote = "KITTI ATE is 0.12 m versus 0.20 m baseline."
        claim = claim_on_page(document, quote, page_number=1)
        failure = self.checker.check(claim, document)
        self.assertTrue(failure.hard_reject)

        relocation = self.relocator.relocate(claim, document, failure)

        self.assertIsNotNone(relocation)
        self.assertEqual(relocation.page_start, 2)
        self.assertEqual(relocation.method, "quote_found_on_another_page")

    def test_finds_a_quote_split_across_two_pages(self):
        document = make_document()
        document = document.model_copy(
            update={
                "pages": [
                    Page(page_number=1, text="Method\nThe method improves"),
                    Page(page_number=2, text="ATE from 0.20 m to 0.12 m."),
                ],
                "sections": [],
            }
        )
        claim = claim_on_page(
            document, "The method improves\nATE from 0.20 m", page_number=1
        )
        failure = self.checker.check(claim, document)
        self.assertTrue(failure.hard_reject)

        relocation = self.relocator.relocate(claim, document, failure)

        self.assertIsNotNone(relocation)
        self.assertEqual((relocation.page_start, relocation.page_end), (1, 2))
        self.assertEqual(relocation.method, "quote_spans_pages")

    def test_declines_a_quote_that_is_not_in_the_paper(self):
        """The rejection is doing its job; relocation must not rescue it."""
        document = make_document()
        claim = claim_on_page(document, "quantum annealing wins", page_number=1)
        failure = self.checker.check(claim, document)

        self.assertIsNone(self.relocator.relocate(claim, document, failure))

    def test_declines_when_the_evidence_belongs_to_another_paper(self):
        """A paper mismatch is not a location problem.

        Moving the coordinates would attach the claim to a document it never
        came from, which is the one thing relocation must never do.
        """
        document = make_document()
        other = make_document()
        claim = claim_on_page(other, "KITTI ATE is 0.12 m versus 0.20 m baseline.", 2)
        failure = self.checker.check(claim, document)

        self.assertIsNone(self.relocator.relocate(claim, document, failure))

    def test_a_relocation_cannot_carry_a_claim_quote_or_paper(self):
        """The guardrail is the type, not a rule a strategy is asked to follow."""
        fields = set(EvidenceRelocation.model_fields)

        self.assertNotIn("claim", fields)
        self.assertNotIn("quote", fields)
        self.assertNotIn("paper_id", fields)


class FakeLLMVerifier:
    def __init__(self):
        self.calls = []

    def verify(self, claim, deterministic, document):
        self.calls.append(claim)
        raise AssertionError("not reached in these tests")


class TestVerifierAppeal(unittest.TestCase):
    """The appeal changes where the checker looks, and nothing else."""

    def setUp(self):
        self.checker = DeterministicEvidenceChecker()

    def test_without_a_relocator_a_rejection_is_final(self):
        document = make_document()
        claim = claim_on_page(
            document, "KITTI ATE is 0.12 m versus 0.20 m baseline.", 1
        )
        verifier = EvidenceVerifier(FakeLLMVerifier(), self.checker)

        claim_out, result = verifier._appeal(
            claim, document, self.checker.check(claim, document)
        )

        self.assertTrue(result.hard_reject)
        self.assertIs(claim_out, claim)

    def test_a_successful_appeal_keeps_the_quote_and_paper(self):
        document = make_document()
        quote = "KITTI ATE is 0.12 m versus 0.20 m baseline."
        claim = claim_on_page(document, quote, page_number=1)
        verifier = EvidenceVerifier(
            FakeLLMVerifier(), self.checker, relocator=FuzzyEvidenceRelocator()
        )

        claim_out, result = verifier._appeal(
            claim, document, self.checker.check(claim, document)
        )

        self.assertFalse(result.hard_reject)
        self.assertEqual(claim_out.evidence.quote, quote)
        self.assertEqual(claim_out.claim, claim.claim)
        self.assertEqual(claim_out.evidence.paper_id, claim.evidence.paper_id)
        self.assertEqual(claim_out.evidence.locator.page_start, 2)

    def test_a_successful_appeal_is_recorded(self):
        """A relocated citation must be visible in the audit trail."""
        document = make_document()
        claim = claim_on_page(
            document, "KITTI ATE is 0.12 m versus 0.20 m baseline.", 1
        )
        verifier = EvidenceVerifier(
            FakeLLMVerifier(), self.checker, relocator=FuzzyEvidenceRelocator()
        )

        _, result = verifier._appeal(
            claim, document, self.checker.check(claim, document)
        )

        self.assertTrue(
            any(warning.startswith("EVIDENCE_RELOCATED:") for warning in result.warnings)
        )

    def test_a_relocator_that_raises_does_not_fail_the_claim(self):
        class Broken:
            def relocate(self, claim, document, failure):
                raise RuntimeError("strategy exploded")

        document = make_document()
        claim = claim_on_page(document, "quantum annealing wins", 1)
        verifier = EvidenceVerifier(FakeLLMVerifier(), self.checker, relocator=Broken())
        failure = self.checker.check(claim, document)

        claim_out, result = verifier._appeal(claim, document, failure)

        self.assertTrue(result.hard_reject)
        self.assertIs(claim_out, claim)

    def test_a_relocation_that_does_not_survive_the_recheck_changes_nothing(self):
        """The relocator proposes; the unchanged deterministic check disposes."""

        class Liar:
            def relocate(self, claim, document, failure):
                return EvidenceRelocation(
                    page_start=1, page_end=1, method="wishful_thinking"
                )

        document = make_document()
        claim = claim_on_page(document, "quantum annealing wins", 2)
        verifier = EvidenceVerifier(FakeLLMVerifier(), self.checker, relocator=Liar())
        failure = self.checker.check(claim, document)

        claim_out, result = verifier._appeal(claim, document, failure)

        self.assertTrue(result.hard_reject)
        self.assertIs(claim_out, claim)


if __name__ == "__main__":
    unittest.main()
