"""Unit tests for bounded structured LLM evidence verification."""

import re
import unittest
from uuid import UUID

from paperpilot.analysis import AnalysisLLMInvocationError
from paperpilot.verification import (
    DeterministicEvidenceChecker,
    EvidenceClaim,
    LLMEvidenceVerifier,
    LLMVerificationError,
    SupportLevel,
    VerificationStatus,
)

from .verification_fixtures import make_decision, make_document, make_evidence


class DecisionLLM:
    model_name = "fake-verifier"

    def __init__(
        self,
        support=SupportLevel.DIRECT,
        status=VerificationStatus.VERIFIED,
        *,
        overclaim=False,
        contradiction=0.0,
    ):
        self.support = support
        self.status = status
        self.overclaim = overclaim
        self.contradiction = contradiction
        self.calls = []

    def generate_structured(self, *, system_prompt, user_prompt, response_model):
        self.calls.append((system_prompt, user_prompt, response_model))
        evidence_id = UUID(re.search(r"Evidence ID: ([0-9a-f-]+)", user_prompt).group(1))
        claim = re.search(r"Claim: (.+)", user_prompt).group(1)
        return make_decision(
            evidence_id,
            claim,
            support=self.support,
            status=self.status,
            entailment=0.9 if self.support is not SupportLevel.UNSUPPORTED else 0.0,
            contradiction=self.contradiction,
            overclaim=self.overclaim,
        )


class InvalidLLM:
    def generate_structured(self, **kwargs):
        return {"not": "the schema"}


class FailingLLM:
    def generate_structured(self, **kwargs):
        raise AnalysisLLMInvocationError("secret provider detail")


def inputs():
    document = make_document()
    evidence = make_evidence(document)
    claim = EvidenceClaim(evidence=evidence, claim=evidence.normalized_fact)
    deterministic = DeterministicEvidenceChecker().check(claim, document)
    return claim, deterministic, document


class TestLLMEvidenceVerifier(unittest.TestCase):
    def test_direct_support(self):
        claim, check, document = inputs()
        decision = LLMEvidenceVerifier(DecisionLLM()).verify(claim, check, document)

        self.assertEqual(decision.support_level, SupportLevel.DIRECT)

    def test_derived_support(self):
        claim, check, document = inputs()
        decision = LLMEvidenceVerifier(
            DecisionLLM(SupportLevel.DERIVED)
        ).verify(claim, check, document)

        self.assertEqual(decision.support_level, SupportLevel.DERIVED)

    def test_inference_support(self):
        claim, check, document = inputs()
        decision = LLMEvidenceVerifier(
            DecisionLLM(SupportLevel.INFERENCE, VerificationStatus.PARTIALLY_SUPPORTED)
        ).verify(claim, check, document)

        self.assertEqual(decision.support_level, SupportLevel.INFERENCE)

    def test_unsupported_claim(self):
        claim, check, document = inputs()
        decision = LLMEvidenceVerifier(
            DecisionLLM(SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED)
        ).verify(claim, check, document)

        self.assertEqual(decision.status, VerificationStatus.REJECTED)

    def test_overclaim_is_preserved(self):
        claim, check, document = inputs()
        decision = LLMEvidenceVerifier(
            DecisionLLM(overclaim=True)
        ).verify(claim, check, document)

        self.assertTrue(decision.overclaim_detected)

    def test_contradiction_is_preserved(self):
        claim, check, document = inputs()
        decision = LLMEvidenceVerifier(
            DecisionLLM(
                SupportLevel.UNSUPPORTED,
                VerificationStatus.CONFLICTED,
                contradiction=0.9,
            )
        ).verify(claim, check, document)

        self.assertEqual(decision.status, VerificationStatus.CONFLICTED)

    def test_requested_response_schema_excludes_trusted_identity_fields(self):
        claim, check, document = inputs()
        llm = DecisionLLM()

        LLMEvidenceVerifier(llm).verify(claim, check, document)

        response_model = llm.calls[0][2]
        self.assertEqual(response_model.__name__, "EvidenceVerificationAssessment")
        self.assertNotIn("evidence_id", response_model.model_fields)
        self.assertNotIn("claim", response_model.model_fields)

    def test_trusted_identity_is_bound_from_the_input(self):
        claim, check, document = inputs()

        decision = LLMEvidenceVerifier(DecisionLLM()).verify(claim, check, document)

        self.assertEqual(decision.evidence_id, claim.evidence.id)
        self.assertEqual(decision.claim, claim.claim)

    def test_enum_values_are_normalized_without_free_text_repair(self):
        class CasingLLM:
            def generate_structured(self, **kwargs):
                return {
                    "support_level": "DIRECT",
                    "status": "PARTIALLY-SUPPORTED",
                    "entailment_score": 0.8,
                    "contradiction_score": 0.0,
                    "overclaim_detected": False,
                    "reasoning": "The quote supports the claim.",
                    "corrected_claim": None,
                    "warnings": [],
                }

        claim, check, document = inputs()
        decision = LLMEvidenceVerifier(CasingLLM()).verify(claim, check, document)

        self.assertEqual(decision.support_level, SupportLevel.DIRECT)
        self.assertEqual(decision.status, VerificationStatus.PARTIALLY_SUPPORTED)

    def test_invalid_schema_is_wrapped(self):
        claim, check, document = inputs()

        with self.assertRaises(LLMVerificationError):
            LLMEvidenceVerifier(InvalidLLM()).verify(claim, check, document)

    def test_provider_failure_is_safely_wrapped(self):
        claim, check, document = inputs()

        with self.assertRaises(LLMVerificationError) as context:
            LLMEvidenceVerifier(FailingLLM()).verify(claim, check, document)
        self.assertNotIn("secret provider detail", str(context.exception))

    def test_prompt_uses_bounded_neighbor_not_entire_document(self):
        claim, check, document = inputs()
        pages = list(document.pages)
        pages[1] = pages[1].model_copy(update={"text": "NEVER_SEND_THIS" * 1000})
        document = document.model_copy(update={"pages": pages})
        llm = DecisionLLM()

        LLMEvidenceVerifier(llm).verify(claim, check, document)

        self.assertNotIn("NEVER_SEND_THIS", llm.calls[0][1])
        self.assertLess(len(llm.calls[0][1]), 5000)

    def test_inputs_are_not_modified(self):
        claim, check, document = inputs()
        before = (
            claim.model_dump(mode="json"),
            check.model_dump(mode="json"),
            document.model_dump(mode="json"),
        )

        LLMEvidenceVerifier(DecisionLLM()).verify(claim, check, document)

        self.assertEqual(claim.model_dump(mode="json"), before[0])
        self.assertEqual(check.model_dump(mode="json"), before[1])
        self.assertEqual(document.model_dump(mode="json"), before[2])


if __name__ == "__main__":
    unittest.main()
