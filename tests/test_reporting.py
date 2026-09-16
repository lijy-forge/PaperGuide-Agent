"""Unit tests for evidence-grounded research report generation."""

import copy
import unittest
from uuid import uuid4

from paperguide.domain import EvidenceType
from paperguide.reporting import (
    ReportCitation,
    ReportClaim,
    ReportContextBuilder,
    ReportSchemaValidationError,
    ReportSection,
    ReportVerificationError,
    ReportVerifier,
    ReportWriterError,
    ResearchReport,
    StructuredReportWriter,
)
from paperguide.verification import (
    EvidenceVerificationResult,
    NumericConsistencyResult,
    SupportLevel,
    VerificationStatus,
    VerifiedEvidence,
    VerifiedPaperAnalysisResult,
)
from pydantic import ValidationError

from .verification_fixtures import make_analysis


def numeric_result():
    """Create an empty deterministic numeric-check result."""

    return NumericConsistencyResult(
        claim_numbers=[],
        quote_numbers=[],
        missing_numbers=[],
        unit_matches=None,
        direction_matches=None,
        warnings=[],
    )


def verified_item(evidence, status, support):
    """Create one completed evidence-verification item."""

    return VerifiedEvidence(
        evidence=evidence,
        claim=evidence.normalized_fact,
        status=status,
        support_level=support,
        entailment_score=(1.0 if status is VerificationStatus.VERIFIED else 0.0),
        contradiction_score=(
            0.9 if status is VerificationStatus.CONFLICTED else 0.0
        ),
        overclaim_detected=False,
        numeric_consistency=numeric_result(),
        reasoning=(
            "Conflicting evidence." if status is VerificationStatus.CONFLICTED
            else "Verification completed."
        ),
        warnings=[],
        verifier_model="fake-verifier",
        prompt_version="v1",
    )


def make_verified_analysis():
    """Create a result containing accepted, rejected, and conflicted evidence."""

    analysis, _ = make_analysis()
    accepted = analysis.evidence[0]
    rejected = analysis.evidence[1].model_copy(
        update={"evidence_type": EvidenceType.UNSUPPORTED},
        deep=True,
    )
    conflicted = rejected.model_copy(update={"id": uuid4()}, deep=True)
    accepted_item = verified_item(
        accepted,
        VerificationStatus.VERIFIED,
        SupportLevel.DIRECT,
    )
    rejected_item = verified_item(
        rejected,
        VerificationStatus.REJECTED,
        SupportLevel.UNSUPPORTED,
    )
    conflicted_item = verified_item(
        conflicted,
        VerificationStatus.CONFLICTED,
        SupportLevel.UNSUPPORTED,
    )
    verification = EvidenceVerificationResult(
        paper_id=analysis.paper_id,
        verified_evidence=[accepted_item, rejected_item, conflicted_item],
        accepted_evidence_ids=[accepted.id],
        rejected_evidence_ids=[rejected.id],
        conflicted_evidence_ids=[conflicted.id],
        conflicts=[],
        warnings=[],
        verification_score=1 / 3,
        total_evidence=3,
        total_verified=1,
        total_partial=0,
        total_rejected=1,
        total_conflicted=1,
    )
    return VerifiedPaperAnalysisResult(
        original_analysis=analysis,
        verification=verification,
        verified_method_summary=analysis.method_summary,
        verified_experiment_summary=analysis.experiment_summary,
        verified_contributions=[],
        verified_limitations=[],
        warnings=[],
    )


def make_context():
    """Create a context containing one accepted evidence item."""

    return ReportContextBuilder().build([make_verified_analysis()])


def make_report(context=None):
    """Create a valid report referencing the first context evidence item."""

    context = context or make_context()
    evidence = context.evidence[0]
    return ResearchReport(
        question="How does the method improve localization?",
        title="Localization Research Report",
        summary="The verified method reports improved localization accuracy.",
        sections=[
            ReportSection(
                title="Method",
                claims=[
                    ReportClaim(
                        text=evidence.normalized_fact,
                        evidence_ids=[evidence.evidence_id],
                    )
                ],
                evidence_ids=[evidence.evidence_id],
            )
        ],
        citations=[
            ReportCitation(
                paper_id=evidence.paper_id,
                evidence_id=evidence.evidence_id,
                quote=evidence.quote,
                locator=evidence.locator,
            )
        ],
        evidence_ids=[evidence.evidence_id],
        warnings=[],
    )


class FakeStructuredLLM:
    """Return configured structured output or a configured failure."""

    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []

    def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.output)


class ReportingTests(unittest.TestCase):
    """Verify report schemas, context filtering, writing, and grounding checks."""

    def test_report_model_json_round_trip(self) -> None:
        report = make_report()

        restored = ResearchReport.model_validate_json(report.model_dump_json())

        self.assertEqual(restored, report)

    def test_report_model_rejects_unknown_fields(self) -> None:
        report = make_report()
        payload = report.model_dump()
        payload["unexpected"] = True

        with self.assertRaises(ValidationError):
            ResearchReport.model_validate(payload)

    def test_context_filters_rejected_and_conflicted_evidence(self) -> None:
        result = make_verified_analysis()

        context = ReportContextBuilder().build([result])

        self.assertEqual(len(context.evidence), 1)
        self.assertEqual(
            context.evidence[0].evidence_id,
            result.verification.accepted_evidence_ids[0],
        )
        self.assertEqual(context.evidence[0].paper_id, result.verification.paper_id)
        self.assertIsNotNone(context.evidence[0].locator)

    def test_context_retains_verified_structured_paper_analysis(self) -> None:
        context = ReportContextBuilder().build([make_verified_analysis()])

        self.assertEqual(len(context.papers), 1)
        self.assertEqual(context.papers[0].title, "Verification Paper")
        self.assertEqual(context.papers[0].method_name, "VerifierNet")
        self.assertEqual(context.papers[0].datasets, ["KITTI"])
        self.assertIn('"record_type":"verified_paper_analysis"', context.context_text)
        self.assertTrue(any("one paper" in item for item in context.warnings))

    def test_context_respects_character_limit(self) -> None:
        context = ReportContextBuilder(max_context_chars=10).build(
            [make_verified_analysis()]
        )

        self.assertLessEqual(context.char_count, 10)
        self.assertTrue(context.truncated)
        self.assertEqual(context.evidence, [])

    def test_context_does_not_modify_input(self) -> None:
        result = make_verified_analysis()
        original = result.model_copy(deep=True)

        ReportContextBuilder().build([result])

        self.assertEqual(result, original)

    def test_writer_uses_structured_report_schema(self) -> None:
        context = make_context()
        expected = make_report(context)
        llm = FakeStructuredLLM(output=expected.model_dump())

        report = StructuredReportWriter(llm).write(expected.question, context)

        self.assertEqual(report.question, expected.question)
        self.assertEqual(report.sections, expected.sections)
        self.assertEqual(report.warnings, expected.warnings)
        self.assertIs(llm.calls[0]["response_model"], ResearchReport)
        self.assertIn("cross-paper comparison", llm.calls[0]["system_prompt"])
        self.assertIn("never infer YOLO", llm.calls[0]["system_prompt"])

    def test_writer_derives_redundant_evidence_declarations(self) -> None:
        context = make_context()
        output = make_report(context)
        output.evidence_ids = []
        output.sections[0].evidence_ids = []

        report = StructuredReportWriter(FakeStructuredLLM(output=output)).write(
            output.question, context
        )

        evidence_id = context.evidence[0].evidence_id
        self.assertEqual(report.sections[0].evidence_ids, [evidence_id])
        self.assertEqual(report.evidence_ids, [evidence_id])
        ReportVerifier().verify(report, context)

    def test_writer_rejects_non_schema_output_without_repair(self) -> None:
        writer = StructuredReportWriter(FakeStructuredLLM(output="free text"))

        with self.assertRaises(ReportSchemaValidationError):
            writer.write("Question", make_context())

    def test_writer_rejects_changed_question(self) -> None:
        context = make_context()
        output = make_report(context).model_copy(
            update={"question": "A different question"}
        )

        with self.assertRaises(ReportSchemaValidationError):
            StructuredReportWriter(FakeStructuredLLM(output=output)).write(
                "Original question",
                context,
            )

    def test_writer_isolates_llm_failure(self) -> None:
        writer = StructuredReportWriter(
            FakeStructuredLLM(error=RuntimeError("provider unavailable"))
        )

        with self.assertRaises(ReportWriterError):
            writer.write("Question", make_context())

    def test_verifier_accepts_grounded_report(self) -> None:
        context = make_context()
        report = make_report(context)

        verified = ReportVerifier().verify(report, context)

        self.assertEqual(verified.sections, report.sections)
        self.assertEqual(verified.evidence_ids, report.evidence_ids)
        self.assertIsNot(verified, report)
        self.assertEqual(verified.citations[0].paper_title, "Verification Paper")
        self.assertTrue(any("one paper" in item for item in verified.warnings))

    def test_verifier_rejects_claim_without_citation(self) -> None:
        context = make_context()
        report = make_report(context)
        report.citations = []

        with self.assertRaises(ReportVerificationError):
            ReportVerifier().verify(report, context)

    def test_verifier_rejects_missing_evidence(self) -> None:
        context = make_context()
        report = make_report(context)
        missing = uuid4()
        report.sections[0].evidence_ids = [missing]
        report.sections[0].claims[0].evidence_ids = [missing]

        with self.assertRaises(ReportVerificationError):
            ReportVerifier().verify(report, context)

    def test_verifier_rejects_citation_paper_mismatch(self) -> None:
        context = make_context()
        report = make_report(context)
        other_paper = uuid4()
        report.citations[0] = report.citations[0].model_copy(
            update={
                "paper_id": other_paper,
                "locator": report.citations[0].locator.model_copy(
                    update={"paper_id": other_paper}
                ),
            }
        )

        with self.assertRaises(ReportVerificationError):
            ReportVerifier().verify(report, context)

    def test_verifier_rejects_quote_not_in_verified_evidence(self) -> None:
        context = make_context()
        report = make_report(context)
        report.citations[0].quote = "Invented quote"

        with self.assertRaises(ReportVerificationError):
            ReportVerifier().verify(report, context)

    def test_unsupported_claim_adds_warning(self) -> None:
        context = make_context()
        report = make_report(context)
        report.sections[0].claims.append(
            ReportClaim(text="A speculative future benefit.", evidence_ids=[])
        )

        verified = ReportVerifier().verify(report, context)

        self.assertTrue(
            any("Unsupported claim" in warning for warning in verified.warnings)
        )

    def test_verifier_does_not_modify_inputs(self) -> None:
        context = make_context()
        report = make_report(context)
        report.sections[0].claims.append(
            ReportClaim(text="A speculative future benefit.", evidence_ids=[])
        )
        original_report = report.model_copy(deep=True)
        original_context = context.model_copy(deep=True)

        ReportVerifier().verify(report, context)

        self.assertEqual(report, original_report)
        self.assertEqual(context, original_context)


if __name__ == "__main__":
    unittest.main()
