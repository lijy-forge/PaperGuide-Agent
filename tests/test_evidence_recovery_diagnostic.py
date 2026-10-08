"""Tests for the per-layer account of rejected evidence.

The counts exist to answer one question: is anything still being lost that
more machinery here could recover? A total of rejections cannot answer it, so
each cause is separated and each has a different fix.
"""

import unittest

from paperguide.document.models import Page
from paperguide.verification import DeterministicEvidenceChecker, EvidenceClaim
from paperguide.verification.diagnostics import (
    PAPER_MISMATCH,
    QUOTE_ABSENT,
    QUOTE_PARAPHRASED,
    classify_rejection,
)

from .verification_fixtures import make_document, make_evidence


def claim_with(document, quote):
    evidence = make_evidence(document)
    locator = evidence.locator.model_copy(
        update={"char_start": None, "char_end": None, "section_title": None}
    )
    evidence = evidence.model_copy(update={"quote": quote, "locator": locator})
    return EvidenceClaim(evidence=evidence, claim="a claim about the quote")


class TestClassifyRejection(unittest.TestCase):
    def test_a_restated_passage_is_named_a_paraphrase(self):
        """The paper says it; the reader did not quote it.

        Searching harder cannot fix this — the wording is not in the paper —
        so it is the reader that needs changing, not the verifier.
        """
        document = make_document()
        claim = claim_with(document, "the method improves ATE from 0.20 to 0.12")

        self.assertEqual(classify_rejection(claim, document), QUOTE_PARAPHRASED)

    def test_a_quote_the_paper_does_not_resemble_is_named_absent(self):
        document = make_document()
        claim = claim_with(
            document, "quantum annealing outperforms every published baseline"
        )

        self.assertEqual(classify_rejection(claim, document), QUOTE_ABSENT)

    def test_evidence_from_another_paper_is_named_a_mismatch(self):
        """Neither a wording problem nor a location one, and never relocatable."""
        document = make_document()
        other = make_document()
        claim = claim_with(other, "KITTI ATE is 0.12 m versus 0.20 m baseline.")

        self.assertEqual(classify_rejection(claim, document), PAPER_MISMATCH)


class FakeAcceptingVerifier:
    model_name = "verification-model"

    def verify(self, claim, deterministic, document):
        from paperguide.verification.models import (
            EvidenceVerificationDecision,
            SupportLevel,
            VerificationStatus,
        )

        return EvidenceVerificationDecision(
            evidence_id=claim.evidence.id,
            claim=claim.claim,
            support_level=SupportLevel.DIRECT,
            status=VerificationStatus.VERIFIED,
            entailment_score=0.9,
            contradiction_score=0.0,
            overclaim_detected=False,
            reasoning="the quote states the claim",
            warnings=[],
        )


class TestRecoveryCounts(unittest.TestCase):
    """The counts must survive the path they are meant to describe."""

    def test_a_clean_paper_reports_nothing_rejected(self):
        from paperguide.verification import EvidenceVerifier

        from .verification_fixtures import make_analysis

        analysis, document = make_analysis()
        verifier = EvidenceVerifier(
            FakeAcceptingVerifier(), DeterministicEvidenceChecker()
        )

        result = verifier.verify(analysis, document)

        self.assertIsNotNone(result.recovery)
        self.assertEqual(result.recovery.hard_rejected, 0)
        self.assertEqual(result.recovery.unrecovered_reasons, {})

    def test_an_unrecoverable_rejection_is_counted_with_its_cause(self):
        from paperguide.verification import EvidenceVerifier

        from .verification_fixtures import make_analysis

        analysis, document = make_analysis()
        # Blank the pages so no quote can be located anywhere in the paper.
        document = document.model_copy(
            update={
                "pages": [
                    Page(page_number=page.page_number, text="unrelated filler text")
                    for page in document.pages
                ],
                "sections": [],
            }
        )
        verifier = EvidenceVerifier(
            FakeAcceptingVerifier(), DeterministicEvidenceChecker()
        )

        result = verifier.verify(analysis, document)

        self.assertGreater(result.recovery.hard_rejected, 0)
        self.assertEqual(result.recovery.recovered, 0)
        self.assertEqual(
            sum(result.recovery.unrecovered_reasons.values()),
            result.recovery.hard_rejected,
        )

    def test_a_recovered_rejection_records_which_strategy_found_it(self):
        from paperguide.verification import EvidenceVerifier
        from paperguide.verification.relocation import FuzzyEvidenceRelocator

        from .verification_fixtures import make_analysis

        analysis, document = make_analysis()
        # Swap the page text so every quote sits on the other page.
        swapped = document.model_copy(
            update={
                "pages": [
                    Page(page_number=1, text=document.pages[1].text),
                    Page(page_number=2, text=document.pages[0].text),
                ],
                "sections": [],
            }
        )
        verifier = EvidenceVerifier(
            FakeAcceptingVerifier(),
            DeterministicEvidenceChecker(),
            relocator=FuzzyEvidenceRelocator(),
        )

        result = verifier.verify(analysis, swapped)

        self.assertGreater(result.recovery.recovered, 0)
        self.assertIn(
            "quote_found_on_another_page", result.recovery.recovery_methods
        )


if __name__ == "__main__":
    unittest.main()
