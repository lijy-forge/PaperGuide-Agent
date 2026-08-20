"""Unit tests for conservative evidence conflict detection."""

import unittest

from paperpilot.verification import (
    EvidenceConflictDetector,
    NumericConsistencyResult,
    SupportLevel,
    VerificationStatus,
    VerifiedEvidence,
    ConflictRecord,
)

from .verification_fixtures import make_document, make_evidence


def item(evidence, claim, *, source="method.summary", status=VerificationStatus.VERIFIED):
    return VerifiedEvidence(
        evidence=evidence,
        claim=claim,
        source_field=source,
        status=status,
        support_level=(
            SupportLevel.UNSUPPORTED
            if status is VerificationStatus.REJECTED
            else SupportLevel.DIRECT
        ),
        entailment_score=0.0 if status is VerificationStatus.REJECTED else 0.9,
        contradiction_score=0.0,
        overclaim_detected=False,
        numeric_consistency=NumericConsistencyResult(
            claim_numbers=[], quote_numbers=[], missing_numbers=[], unit_matches=None,
            direction_matches=None, warnings=[]
        ),
        reasoning="Decision.",
        warnings=[],
        prompt_version="v1",
    )


class TestEvidenceConflictDetector(unittest.TestCase):
    def test_same_claim_with_increase_and_decrease_quotes_conflicts(self):
        document = make_document()
        first = make_evidence(document)
        second = make_evidence(document).model_copy(update={"quote": "ATE decreased"})

        conflicts = EvidenceConflictDetector().detect(
            [item(first, "ATE improved"), item(second, "ATE improved")]
        )

        self.assertTrue(any("direction" in record.conflict_type for record in conflicts))

    def test_same_metric_with_different_values_conflicts(self):
        document = make_document()
        first = item(make_evidence(document), "KITTI ATE 0.12 m", source="experiment.metric:KITTI:ATE")
        second = item(make_evidence(document), "KITTI ATE 0.25 m", source="experiment.metric:KITTI:ATE#2")

        conflicts = EvidenceConflictDetector().detect([first, second])

        self.assertTrue(any(record.conflict_type == "metric_value" for record in conflicts))

    def test_unrelated_evidence_has_no_conflict(self):
        document = make_document()
        first = item(make_evidence(document), "Feature filtering is used")
        second = item(make_evidence(document, page_number=2), "KITTI is evaluated", source="experiment.finding:0")

        self.assertEqual(EvidenceConflictDetector().detect([first, second]), [])

    def test_rejected_claim_does_not_conflict_with_supported_claim_on_same_evidence(self):
        document = make_document()
        evidence = make_evidence(document)
        supported = item(evidence, "The method improves ATE")
        rejected = item(
            evidence,
            "The method guarantees perfect localization",
            status=VerificationStatus.REJECTED,
        )

        conflicts = EvidenceConflictDetector().detect([supported, rejected])

        self.assertEqual(conflicts, [])

    def test_conflict_record_json_round_trip(self):
        record = ConflictRecord(
            evidence_ids=[], claims=["up", "down"], conflict_type="direction",
            description="Opposing directions.", confidence=0.8, warnings=[]
        )

        restored = ConflictRecord.model_validate_json(record.model_dump_json())

        self.assertEqual(restored, record)


if __name__ == "__main__":
    unittest.main()
