"""Unit tests for composed evidence-grounded report generation."""

import copy
import unittest

from paperguide.domain import PaperSource, ResearchConfig
from paperguide.orchestration import create_initial_state
from paperguide.reporting import (
    EvidenceGroundedReportService,
    ReportContext,
    ReportContextBuildError,
    ReportGenerationError,
    ReportVerificationError,
    ReportWritingError,
    ResearchReport,
)
from paperguide.verification import (
    EvidenceVerificationResult,
    VerifiedPaperAnalysisResult,
)

from .verification_fixtures import make_analysis


def make_state(*, include_verified: bool = True):
    """Create a valid state with an optional verified paper result."""

    config = ResearchConfig(
        question="Analyze visual SLAM",
        max_papers=5,
        sources=[PaperSource.ARXIV],
    )
    state = create_initial_state(config.question, config)
    if not include_verified:
        return state

    analysis, document = make_analysis()
    verification = EvidenceVerificationResult(
        paper_id=analysis.paper_id,
        verified_evidence=[],
        accepted_evidence_ids=[],
        rejected_evidence_ids=[],
        conflicted_evidence_ids=[],
        conflicts=[],
        warnings=[],
        verification_score=0.0,
        total_evidence=0,
        total_verified=0,
        total_partial=0,
        total_rejected=0,
        total_conflicted=0,
    )
    verified = VerifiedPaperAnalysisResult(
        original_analysis=analysis,
        verification=verification,
        verified_method_summary=analysis.method_summary,
        verified_experiment_summary=analysis.experiment_summary,
        verified_contributions=[],
        verified_limitations=[],
        warnings=[],
    )
    key = str(document.paper_id)
    state["documents"] = {key: document}
    state["analyses"] = {key: analysis}
    state["verification_results"] = {key: verification}
    state["verified_results"] = {key: verified}
    return state


def make_context() -> ReportContext:
    """Create a bounded empty context for orchestration-only tests."""

    return ReportContext(
        paper_ids=[],
        evidence=[],
        context_text="",
        char_count=0,
        max_chars=100,
        total_available_evidence=0,
        truncated=False,
        warnings=[],
    )


def make_report(question: str) -> ResearchReport:
    """Create a minimal schema-valid report."""

    return ResearchReport(
        question=question,
        title="Visual SLAM Report",
        summary="A structured summary.",
        sections=[],
        citations=[],
        evidence_ids=[],
        warnings=[],
    )


class FakeContextBuilder:
    """Return a configured context or failure and record inputs."""

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def build(self, results):
        self.calls.append(copy.deepcopy(results))
        if self.error is not None:
            raise self.error
        return make_context()


class FakeWriter:
    """Return a structured report or a configured failure."""

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def write(self, question, context):
        self.calls.append((question, context.model_copy(deep=True)))
        if self.error is not None:
            raise self.error
        return make_report(question)


class FakeVerifier:
    """Return an isolated report or a configured verification failure."""

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def verify(self, report, context):
        self.calls.append(
            (report.model_copy(deep=True), context.model_copy(deep=True))
        )
        if self.error is not None:
            raise self.error
        return report.model_copy(deep=True)


def make_service(context_builder=None, writer=None, verifier=None):
    """Create a report service entirely from fake injected dependencies."""

    return EvidenceGroundedReportService(
        context_builder or FakeContextBuilder(),
        writer or FakeWriter(),
        verifier or FakeVerifier(),
    )


class ReportServiceTests(unittest.TestCase):
    """Verify composition, typed failures, compatibility, and state isolation."""

    def test_generates_verified_report(self) -> None:
        state = make_state()

        report = make_service().generate(state)

        self.assertEqual(report.question, state["question"])
        self.assertEqual(report.title, "Visual SLAM Report")

    def test_empty_verified_results_are_rejected(self) -> None:
        builder = FakeContextBuilder()

        with self.assertRaises(ReportContextBuildError):
            make_service(context_builder=builder).generate(
                make_state(include_verified=False)
            )

        self.assertEqual(builder.calls, [])

    def test_context_failure_is_wrapped(self) -> None:
        builder = FakeContextBuilder(error=RuntimeError("context failed"))

        with self.assertRaises(ReportContextBuildError) as captured:
            make_service(context_builder=builder).generate(make_state())

        self.assertIsInstance(captured.exception.__cause__, RuntimeError)

    def test_writer_failure_is_wrapped(self) -> None:
        writer = FakeWriter(error=RuntimeError("writer failed"))

        with self.assertRaises(ReportWritingError) as captured:
            make_service(writer=writer).generate(make_state())

        self.assertIsInstance(captured.exception.__cause__, RuntimeError)

    def test_verifier_failure_is_wrapped(self) -> None:
        verifier = FakeVerifier(error=RuntimeError("verification failed"))

        with self.assertRaises(ReportVerificationError) as captured:
            make_service(verifier=verifier).generate(make_state())

        self.assertIsInstance(captured.exception.__cause__, RuntimeError)

    def test_state_is_not_modified(self) -> None:
        state = make_state()
        original = copy.deepcopy(state)

        make_service().generate(state)

        self.assertEqual(state, original)

    def test_injected_dependencies_are_used_in_order(self) -> None:
        builder = FakeContextBuilder()
        writer = FakeWriter()
        verifier = FakeVerifier()
        state = make_state()

        make_service(builder, writer, verifier).generate(state)

        self.assertEqual(len(builder.calls), 1)
        self.assertEqual(len(writer.calls), 1)
        self.assertEqual(len(verifier.calls), 1)
        self.assertEqual(writer.calls[0][0], state["question"])

    def test_existing_application_protocol_signature_is_supported(self) -> None:
        state = make_state()
        results = list(state["verified_results"].values())

        report = make_service().generate(state["question"], results)

        self.assertEqual(report.question, state["question"])

    def test_compatibility_signature_requires_results(self) -> None:
        with self.assertRaises(ReportGenerationError):
            make_service().generate("Question", None)


if __name__ == "__main__":
    unittest.main()
