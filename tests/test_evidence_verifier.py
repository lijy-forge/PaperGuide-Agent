"""Unit tests for verification orchestration, scoring, and analysis filtering."""

import re
import unittest
from uuid import UUID

from paperguide.analysis import AnalysisLLMInvocationError
from paperguide.verification import (
    DeterministicEvidenceChecker,
    EvidenceVerifier,
    LLMEvidenceVerifier,
    SupportLevel,
    VerificationInputError,
    VerificationScorer,
    VerificationStatus,
    apply_verification,
)

from .verification_fixtures import make_analysis, make_decision, make_evidence


class QueueDecisionLLM:
    model_name = "verification-model"

    def __init__(self, decisions=None, *, fail_calls=None, warning=""):
        self.decisions = decisions or []
        self.fail_calls = set(fail_calls or [])
        self.warning = warning
        self.calls = []

    def generate_structured(self, *, system_prompt, user_prompt, response_model):
        call_index = len(self.calls)
        self.calls.append((system_prompt, user_prompt, response_model))
        if call_index in self.fail_calls:
            raise AnalysisLLMInvocationError("provider failure")
        evidence_id = UUID(re.search(r"Evidence ID: ([0-9a-f-]+)", user_prompt).group(1))
        claim = re.search(r"Claim: (.+)", user_prompt).group(1)
        support, status = (
            self.decisions[call_index]
            if call_index < len(self.decisions)
            else (SupportLevel.DIRECT, VerificationStatus.VERIFIED)
        )
        decision = make_decision(
            evidence_id,
            claim,
            support=support,
            status=status,
            entailment=0.0 if support is SupportLevel.UNSUPPORTED else 1.0,
        )
        if self.warning:
            decision = decision.model_copy(update={"warnings": [self.warning, self.warning]})
        return decision


def verifier(llm):
    return EvidenceVerifier(
        LLMEvidenceVerifier(llm),
        DeterministicEvidenceChecker(),
    )


class NoConflictDetector:
    def detect(self, items):
        return []


class FailingChecker:
    def check(self, claim, document):
        raise RuntimeError("deterministic failure")


class TestEvidenceVerifier(unittest.TestCase):
    def test_complete_verification_succeeds(self):
        analysis, document = make_analysis()

        result = verifier(QueueDecisionLLM()).verify(analysis, document)

        self.assertEqual(result.total_evidence, 2)
        self.assertEqual(result.total_verified, 2)
        self.assertEqual(len(result.accepted_evidence_ids), 2)

    def test_page_relative_offsets_remain_valid_inside_longer_section_text(self):
        analysis, document = make_analysis()
        sections = list(document.sections)
        sections[0] = sections[0].model_copy(
            update={"text": f"Earlier section material.\n{sections[0].text}"}
        )
        document = document.model_copy(update={"sections": sections}, deep=True)
        llm = QueueDecisionLLM()

        result = verifier(llm).verify(analysis, document)

        self.assertIn(
            analysis.method_summary.evidence_ids[0],
            result.accepted_evidence_ids,
        )
        self.assertEqual(len(llm.calls), 2)

    def test_missing_quote_direction_is_unknown_not_a_conflict(self):
        analysis, document = make_analysis()
        evidence = list(analysis.evidence)
        neutral_quote = "The method reports ATE values of 0.20 m and 0.12 m."
        page_text = f"Method\n{neutral_quote}"
        pages = list(document.pages)
        pages[0] = pages[0].model_copy(update={"text": page_text})
        sections = list(document.sections)
        sections[0] = sections[0].model_copy(update={"text": page_text})
        locator = evidence[0].locator.model_copy(
            update={
                "char_start": len("Method\n"),
                "char_end": len(page_text),
            }
        )
        evidence[0] = evidence[0].model_copy(
            update={"quote": neutral_quote, "locator": locator}
        )
        analysis = analysis.model_copy(update={"evidence": evidence}, deep=True)
        document = document.model_copy(
            update={"pages": pages, "sections": sections}, deep=True
        )

        result = verifier(QueueDecisionLLM()).verify(analysis, document)

        method_items = [
            item
            for item in result.verified_evidence
            if item.evidence.id == evidence[0].id
        ]
        self.assertTrue(method_items)
        self.assertTrue(
            all(item.numeric_consistency.direction_matches is None for item in method_items)
        )
        self.assertNotIn(evidence[0].id, result.conflicted_evidence_ids)
        self.assertIn(evidence[0].id, result.accepted_evidence_ids)

    def test_hard_reject_does_not_call_llm(self):
        analysis, document = make_analysis()
        evidence = list(analysis.evidence)
        locator = evidence[0].locator.model_copy(update={"char_end": 9999})
        evidence[0] = evidence[0].model_copy(update={"locator": locator})
        analysis = analysis.model_copy(update={"evidence": evidence}, deep=True)
        llm = QueueDecisionLLM()

        result = verifier(llm).verify(analysis, document)

        self.assertEqual(len(llm.calls), 1)
        self.assertIn(evidence[0].id, result.rejected_evidence_ids)

    def test_single_llm_failure_does_not_stop_batch(self):
        analysis, document = make_analysis()
        llm = QueueDecisionLLM(fail_calls={0})

        result = verifier(llm).verify(analysis, document)

        self.assertEqual(result.total_rejected, 1)
        self.assertEqual(result.total_verified, 1)

    def test_single_deterministic_failure_is_rejected_without_llm(self):
        analysis, document = make_analysis()
        llm = QueueDecisionLLM()
        evidence_verifier = EvidenceVerifier(
            LLMEvidenceVerifier(llm),
            FailingChecker(),
        )

        result = evidence_verifier.verify(analysis, document)

        self.assertEqual(result.total_rejected, 2)
        self.assertEqual(llm.calls, [])

    def test_accepted_and_rejected_ids_are_correct(self):
        analysis, document = make_analysis()
        llm = QueueDecisionLLM(
            decisions=[
                (SupportLevel.DIRECT, VerificationStatus.VERIFIED),
                (SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED),
            ]
        )

        result = verifier(llm).verify(analysis, document)

        self.assertEqual(result.accepted_evidence_ids, [analysis.evidence[0].id])
        self.assertEqual(result.rejected_evidence_ids, [analysis.evidence[1].id])

    def test_one_rejected_claim_does_not_poison_supported_evidence(self):
        analysis, document = make_analysis()
        method = analysis.method_summary.model_copy(
            update={"innovations": ["An unsupported extra innovation claim."]}
        )
        expanded = analysis.model_copy(
            update={"method_summary": method},
            deep=True,
        )
        llm = QueueDecisionLLM(
            decisions=[
                (SupportLevel.DIRECT, VerificationStatus.VERIFIED),
                (SupportLevel.DIRECT, VerificationStatus.VERIFIED),
                (SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED),
            ]
        )
        verification = EvidenceVerifier(
            LLMEvidenceVerifier(llm),
            DeterministicEvidenceChecker(),
        ).verify(expanded, document)

        self.assertIn(
            analysis.method_summary.evidence_ids[0],
            verification.accepted_evidence_ids,
        )
        filtered = apply_verification(expanded, verification)
        self.assertEqual(
            filtered.verified_method_summary.evidence_ids,
            analysis.method_summary.evidence_ids,
        )

    def test_verified_direct_score_is_one(self):
        analysis, document = make_analysis()

        result = verifier(QueueDecisionLLM()).verify(analysis, document)

        self.assertEqual(result.verification_score, 1.0)
        self.assertEqual(VerificationScorer.score_item(result.verified_evidence[0]), 1.0)

    def test_overclaim_and_contradiction_reduce_score(self):
        analysis, document = make_analysis()
        llm = QueueDecisionLLM()
        result = verifier(llm).verify(analysis, document)
        penalized = result.verified_evidence[0].model_copy(
            update={"overclaim_detected": True, "contradiction_score": 0.5}
        )

        self.assertLess(VerificationScorer.score_item(penalized), 0.5)

    def test_warnings_are_stably_deduplicated(self):
        analysis, document = make_analysis()

        result = verifier(QueueDecisionLLM(warning="Review needed.")).verify(
            analysis, document
        )

        self.assertEqual(result.warnings.count("Review needed."), 1)

    def test_inputs_are_not_modified(self):
        analysis, document = make_analysis()
        analysis_before = analysis.model_dump(mode="json")
        document_before = document.model_dump(mode="json")

        verifier(QueueDecisionLLM()).verify(analysis, document)

        self.assertEqual(analysis.model_dump(mode="json"), analysis_before)
        self.assertEqual(document.model_dump(mode="json"), document_before)

    def test_all_rejected_returns_zero_score(self):
        analysis, document = make_analysis()
        rejected = [
            (SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED),
            (SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED),
        ]

        result = verifier(QueueDecisionLLM(decisions=rejected)).verify(
            analysis, document
        )

        self.assertEqual(result.total_rejected, 2)
        self.assertEqual(result.verification_score, 0.0)

    def test_empty_evidence_returns_empty_result(self):
        analysis, document = make_analysis()
        method = analysis.method_summary.model_copy(update={"evidence_ids": []})
        experiment = analysis.experiment_summary.model_copy(update={"evidence_ids": []})
        empty = analysis.model_copy(
            update={"method_summary": method, "experiment_summary": experiment, "evidence": []}
        )

        result = verifier(QueueDecisionLLM()).verify(empty, document)

        self.assertEqual(result.total_evidence, 0)
        self.assertEqual(result.verification_score, 0.0)

    def test_paper_id_mismatch_is_an_overall_error(self):
        analysis, _ = make_analysis()
        _, other_document = make_analysis()

        with self.assertRaises(VerificationInputError):
            verifier(QueueDecisionLLM()).verify(analysis, other_document)

    def test_model_name_and_prompt_version_are_recorded(self):
        analysis, document = make_analysis()

        result = verifier(QueueDecisionLLM()).verify(analysis, document)

        self.assertTrue(
            all(item.verifier_model == "verification-model" for item in result.verified_evidence)
        )
        self.assertTrue(all(item.prompt_version == "v1" for item in result.verified_evidence))

    def test_direction_conflict_populates_conflicted_ids(self):
        analysis, document = make_analysis()
        pages = list(document.pages)
        changed_text = "Method\nThe method reduces ATE from 0.20 m to 0.12 m."
        pages[0] = pages[0].model_copy(update={"text": changed_text})
        sections = list(document.sections)
        sections[0] = sections[0].model_copy(update={"text": changed_text})
        document = document.model_copy(update={"pages": pages, "sections": sections})
        evidence = list(analysis.evidence)
        changed_quote = changed_text.split("\n", 1)[1]
        locator = evidence[0].locator.model_copy(
            update={"char_start": len("Method\n"), "char_end": len(changed_text)}
        )
        evidence[0] = evidence[0].model_copy(
            update={"quote": changed_quote, "locator": locator}
        )
        analysis = analysis.model_copy(update={"evidence": evidence}, deep=True)

        result = verifier(QueueDecisionLLM()).verify(analysis, document)

        self.assertIn(evidence[0].id, result.conflicted_evidence_ids)
        self.assertNotIn(evidence[0].id, result.accepted_evidence_ids)


class TestApplyVerification(unittest.TestCase):
    def test_accepted_evidence_is_retained(self):
        analysis, document = make_analysis()
        verification = verifier(QueueDecisionLLM()).verify(analysis, document)

        filtered = apply_verification(analysis, verification)

        self.assertEqual(
            filtered.verified_method_summary.evidence_ids,
            analysis.method_summary.evidence_ids,
        )

    def test_rejected_method_evidence_is_removed_when_another_is_accepted(self):
        analysis, document = make_analysis()
        second = make_evidence(document, page_number=1)
        method = analysis.method_summary.model_copy(
            update={"evidence_ids": [analysis.evidence[0].id, second.id]}
        )
        expanded = analysis.model_copy(
            update={"method_summary": method, "evidence": [*analysis.evidence, second]},
            deep=True,
        )
        llm = QueueDecisionLLM(
            decisions=[
                (SupportLevel.DIRECT, VerificationStatus.VERIFIED),
                (SupportLevel.DIRECT, VerificationStatus.VERIFIED),
                (SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED),
            ]
        )
        verification = EvidenceVerifier(
            LLMEvidenceVerifier(llm),
            DeterministicEvidenceChecker(),
            conflict_detector=NoConflictDetector(),
        ).verify(expanded, document)

        filtered = apply_verification(expanded, verification)

        self.assertEqual(filtered.verified_method_summary.evidence_ids, [analysis.evidence[0].id])

    def test_no_accepted_method_evidence_preserves_verified_experiment(self):
        analysis, document = make_analysis()
        decisions = [
            (SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED),
            (SupportLevel.DIRECT, VerificationStatus.VERIFIED),
        ]
        verification = verifier(QueueDecisionLLM(decisions=decisions)).verify(
            analysis, document
        )

        filtered = apply_verification(analysis, verification)

        self.assertEqual(filtered.verified_method_summary.evidence_ids, [])
        self.assertEqual(filtered.verified_method_summary.innovations, [])
        self.assertEqual(filtered.verified_method_summary.confidence, 0.0)
        self.assertEqual(
            filtered.verified_experiment_summary.evidence_ids,
            analysis.experiment_summary.evidence_ids,
        )
        self.assertTrue(any("Method fields were removed" in item for item in filtered.warnings))

    def test_no_accepted_evidence_fails(self):
        analysis, document = make_analysis()
        decisions = [
            (SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED),
            (SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED),
        ]
        verification = verifier(QueueDecisionLLM(decisions=decisions)).verify(
            analysis, document
        )

        with self.assertRaises(VerificationInputError):
            apply_verification(analysis, verification)

    def test_unverified_experiment_fields_are_removed(self):
        analysis, document = make_analysis()
        decisions = [
            (SupportLevel.DIRECT, VerificationStatus.VERIFIED),
            (SupportLevel.UNSUPPORTED, VerificationStatus.REJECTED),
        ]
        verification = verifier(QueueDecisionLLM(decisions=decisions)).verify(
            analysis, document
        )

        filtered = apply_verification(analysis, verification)

        self.assertEqual(filtered.verified_experiment_summary.metrics, {})
        self.assertEqual(filtered.verified_experiment_summary.datasets, [])

    def test_apply_does_not_modify_original_analysis(self):
        analysis, document = make_analysis()
        verification = verifier(QueueDecisionLLM()).verify(analysis, document)
        before = analysis.model_dump(mode="json")

        apply_verification(analysis, verification)

        self.assertEqual(analysis.model_dump(mode="json"), before)

    def test_unfilterable_fields_have_stable_warning(self):
        analysis, document = make_analysis()
        verification = verifier(QueueDecisionLLM()).verify(analysis, document)

        filtered = apply_verification(analysis, verification)

        self.assertEqual(filtered.verified_contributions, [])
        self.assertEqual(filtered.verified_limitations, [])
        self.assertEqual(len(filtered.warnings), len(set(filtered.warnings)))
        self.assertTrue(any("associations" in warning for warning in filtered.warnings))


if __name__ == "__main__":
    unittest.main()
