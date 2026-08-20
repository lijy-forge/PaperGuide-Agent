"""Unit tests for evidence-verification Pydantic contracts and claim building."""

import unittest
from uuid import uuid4

from pydantic import ValidationError

from paperpilot.verification import (
    EvidenceVerificationDecision,
    EvidenceVerificationResult,
    NumericConsistencyResult,
    SupportLevel,
    VerificationInputError,
    VerificationStatus,
    VerifiedEvidence,
    build_evidence_claims,
)

from .verification_fixtures import make_analysis, make_decision, make_document, make_evidence


def numeric_ok() -> NumericConsistencyResult:
    return NumericConsistencyResult(
        claim_numbers=[],
        quote_numbers=[],
        missing_numbers=[],
        unit_matches=None,
        direction_matches=None,
        warnings=[],
    )


def verified_item():
    document = make_document()
    evidence = make_evidence(document)
    return VerifiedEvidence(
        evidence=evidence,
        claim=evidence.normalized_fact,
        claim_type="method",
        source_field="method.summary",
        status=VerificationStatus.VERIFIED,
        support_level=SupportLevel.DIRECT,
        entailment_score=1.0,
        contradiction_score=0.0,
        overclaim_detected=False,
        numeric_consistency=numeric_ok(),
        reasoning="Directly stated.",
        warnings=[],
        verifier_model="fake",
        prompt_version="v1",
    )


class TestVerificationModels(unittest.TestCase):
    def test_decision_can_be_created(self):
        decision = make_decision(uuid4(), "A supported claim")

        self.assertEqual(decision.status, VerificationStatus.VERIFIED)

    def test_verified_cannot_be_unsupported(self):
        with self.assertRaises(ValidationError):
            make_decision(uuid4(), "Claim", support=SupportLevel.UNSUPPORTED)

    def test_rejected_high_support_is_invalid(self):
        with self.assertRaises(ValidationError):
            make_decision(
                uuid4(),
                "Claim",
                support=SupportLevel.DIRECT,
                status=VerificationStatus.REJECTED,
                entailment=0.8,
            )

    def test_conflicted_requires_conflict_signal(self):
        with self.assertRaises(ValidationError):
            make_decision(
                uuid4(),
                "Claim",
                status=VerificationStatus.CONFLICTED,
                contradiction=0.0,
            )

    def test_verified_evidence_json_round_trip(self):
        item = verified_item()

        restored = VerifiedEvidence.model_validate_json(item.model_dump_json())

        self.assertEqual(restored, item)

    def test_result_statistics_are_validated(self):
        item = verified_item()

        with self.assertRaises(ValidationError):
            EvidenceVerificationResult(
                paper_id=item.evidence.paper_id,
                verified_evidence=[item],
                accepted_evidence_ids=[item.evidence.id],
                rejected_evidence_ids=[],
                conflicted_evidence_ids=[],
                warnings=[],
                verification_score=1.0,
                total_evidence=1,
                total_verified=0,
                total_partial=0,
                total_rejected=0,
                total_conflicted=0,
            )

    def test_result_rejects_foreign_paper_evidence(self):
        item = verified_item()

        with self.assertRaises(ValidationError):
            EvidenceVerificationResult(
                paper_id=uuid4(),
                verified_evidence=[item],
                accepted_evidence_ids=[item.evidence.id],
                rejected_evidence_ids=[],
                conflicted_evidence_ids=[],
                warnings=[],
                verification_score=1.0,
                total_evidence=1,
                total_verified=1,
                total_partial=0,
                total_rejected=0,
                total_conflicted=0,
            )

    def test_result_rejects_duplicate_ids(self):
        item = verified_item()

        with self.assertRaises(ValidationError):
            EvidenceVerificationResult(
                paper_id=item.evidence.paper_id,
                verified_evidence=[item],
                accepted_evidence_ids=[item.evidence.id, item.evidence.id],
                rejected_evidence_ids=[],
                conflicted_evidence_ids=[],
                warnings=[],
                verification_score=1.0,
                total_evidence=1,
                total_verified=1,
                total_partial=0,
                total_rejected=0,
                total_conflicted=0,
            )

    def test_result_json_round_trip(self):
        item = verified_item()
        result = EvidenceVerificationResult(
            paper_id=item.evidence.paper_id,
            verified_evidence=[item],
            accepted_evidence_ids=[item.evidence.id],
            rejected_evidence_ids=[],
            conflicted_evidence_ids=[],
            warnings=[],
            verification_score=1.0,
            total_evidence=1,
            total_verified=1,
            total_partial=0,
            total_rejected=0,
            total_conflicted=0,
        )

        restored = EvidenceVerificationResult.model_validate_json(
            result.model_dump_json()
        )

        self.assertEqual(restored, result)


class TestEvidenceClaimBuilding(unittest.TestCase):
    def test_builds_one_normalized_claim_for_method_evidence(self):
        analysis, _ = make_analysis()

        claims = build_evidence_claims(analysis)

        self.assertEqual(claims[0].source_field, "method.evidence")
        self.assertEqual(claims[0].claim, analysis.evidence[0].normalized_fact)

    def test_builds_one_normalized_claim_for_experiment_evidence(self):
        analysis, _ = make_analysis()

        claims = build_evidence_claims(analysis)

        experiment = next(
            item for item in claims if item.claim_type == "experiment_evidence"
        )
        self.assertEqual(
            experiment.claim,
            analysis.evidence[1].normalized_fact,
        )

    def test_innovations_do_not_multiply_evidence_claims(self):
        analysis, _ = make_analysis()
        method = analysis.method_summary.model_copy(
            update={"innovations": ["A new filtering strategy."]}, deep=True
        )
        analysis = analysis.model_copy(update={"method_summary": method}, deep=True)

        claims = build_evidence_claims(analysis)
        method_ids = [
            item.evidence.id
            for item in claims
            if item.claim_type.startswith("method")
        ]

        self.assertEqual(len(method_ids), 1)
        self.assertEqual(len(set(method_ids)), 1)

    def test_missing_evidence_id_raises_input_error(self):
        analysis, _ = make_analysis()
        broken_method = analysis.method_summary.model_copy(
            update={"evidence_ids": [uuid4()]}, deep=True
        )
        broken = analysis.model_copy(update={"method_summary": broken_method}, deep=True)

        with self.assertRaises(VerificationInputError):
            build_evidence_claims(broken)

    def test_claim_building_does_not_modify_analysis(self):
        analysis, _ = make_analysis()
        before = analysis.model_dump(mode="json")

        build_evidence_claims(analysis)

        self.assertEqual(analysis.model_dump(mode="json"), before)


if __name__ == "__main__":
    unittest.main()
