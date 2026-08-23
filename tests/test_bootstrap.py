"""Tests for the PaperPilot composition root and dependency container."""

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from paperpilot.application import (
    InMemoryTaskStore,
    ResearchRequest,
    ResearchTaskStatus,
)
from paperpilot.bootstrap import (
    ApplicationContainer,
    BootstrapConfig,
    LLMProviderConfig,
    PdfDownloadConfig,
    create_application,
)
from paperpilot.domain import PaperSource
from paperpilot.export import ExportFormat
from paperpilot.orchestration import NextAction, OrchestratorConfig, ResearchStep
from paperpilot.reporting import (
    ReportCitation,
    ReportClaim,
    ReportSection,
    ResearchReport,
)
from paperpilot.verification import (
    EvidenceVerificationResult,
    NumericConsistencyResult,
    SupportLevel,
    VerificationStatus,
    VerifiedEvidence,
    VerifiedPaperAnalysisResult,
)

from .verification_fixtures import make_analysis


class FakeRetriever:
    """Network-free retriever boundary used only for assembly tests."""

    source = PaperSource.ARXIV

    def search(self, query: str, max_results: int = 10):
        return []


class LLMProviderConfigTests(unittest.TestCase):
    def test_request_timeout_is_bounded_and_non_secret(self):
        self.assertEqual(LLMProviderConfig(provider="deepseek").request_timeout_seconds, 180.0)
        with self.assertRaises(ValidationError):
            LLMProviderConfig(provider="deepseek", request_timeout_seconds=0)
        with self.assertRaises(ValidationError):
            LLMProviderConfig(provider="deepseek", request_timeout_seconds=601)


class FakeStructuredLLM:
    """Return one configured report without making an external LLM call."""

    model_name = "fake-structured-model"

    def __init__(self, report: ResearchReport | None = None):
        self.report = report
        self.calls = []

    def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["response_model"] is ResearchReport and self.report is not None:
            return self.report.model_copy(deep=True)
        raise AssertionError("fake LLM received an unexpected model request")


class FakeCompleteGraph:
    """Complete a valid state using one pre-verified paper result."""

    def __init__(self, analysis, document, verification, verified):
        self.analysis = analysis
        self.document = document
        self.verification = verification
        self.verified = verified
        self.inputs = []

    def invoke(self, state):
        self.inputs.append(copy.deepcopy(state))
        result = copy.deepcopy(state)
        key = str(self.document.paper_id)
        result["documents"] = {key: self.document.model_copy(deep=True)}
        result["analyses"] = {key: self.analysis.model_copy(deep=True)}
        result["verification_results"] = {
            key: self.verification.model_copy(deep=True)
        }
        result["verified_results"] = {key: self.verified.model_copy(deep=True)}
        result["current_step"] = ResearchStep.QUALITY_GATE
        result["next_action"] = NextAction.COMPLETE
        return result


class CapturingGraphFactory:
    """Capture all injected nodes and return a selected fake graph."""

    def __init__(self, graph=None):
        self.graph = graph or FakeTerminalGraph()
        self.calls = []

    def __call__(self, *nodes):
        self.calls.append(nodes)
        return self.graph


class FakeTerminalGraph:
    """Minimal graph placeholder for construction-only tests."""

    def invoke(self, state):
        result = copy.deepcopy(state)
        result["current_step"] = ResearchStep.FAILED
        result["next_action"] = NextAction.ABORT
        return result


def make_verified_result():
    """Create one accepted evidence result and its source objects."""

    analysis, document = make_analysis()
    evidence = analysis.evidence[0]
    numeric = NumericConsistencyResult(
        claim_numbers=[],
        quote_numbers=[],
        missing_numbers=[],
        unit_matches=None,
        direction_matches=None,
        warnings=[],
    )
    verified_evidence = VerifiedEvidence(
        evidence=evidence,
        claim=evidence.normalized_fact,
        source_field="method.summary",
        status=VerificationStatus.VERIFIED,
        support_level=SupportLevel.DIRECT,
        entailment_score=1.0,
        contradiction_score=0.0,
        overclaim_detected=False,
        numeric_consistency=numeric,
        reasoning="The quote directly supports the claim.",
        warnings=[],
        verifier_model="fake-verifier",
        prompt_version="test-v1",
    )
    verification = EvidenceVerificationResult(
        paper_id=analysis.paper_id,
        verified_evidence=[verified_evidence],
        accepted_evidence_ids=[evidence.id],
        rejected_evidence_ids=[],
        conflicted_evidence_ids=[],
        conflicts=[],
        warnings=[],
        verification_score=1.0,
        total_evidence=1,
        total_verified=1,
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
    return analysis, document, verification, verified


def make_report(question, verified):
    """Create a report grounded in the accepted evidence fixture."""

    item = verified.verification.verified_evidence[0]
    evidence = item.evidence
    return ResearchReport(
        question=question,
        title="Bootstrap Research Report",
        summary="The verified paper supports the reported method finding.",
        sections=[
            ReportSection(
                title="Findings",
                claims=[
                    ReportClaim(
                        text=evidence.normalized_fact,
                        evidence_ids=[evidence.id],
                    )
                ],
                evidence_ids=[evidence.id],
            )
        ],
        citations=[
            ReportCitation(
                paper_id=evidence.paper_id,
                evidence_id=evidence.id,
                quote=evidence.quote,
                locator=evidence.locator,
            )
        ],
        evidence_ids=[evidence.id],
        warnings=[],
    )


def make_config(root: Path, *, minimum_score: float = 0.7):
    """Create isolated non-secret bootstrap configuration."""

    return BootstrapConfig(
        llm_provider=LLMProviderConfig(provider="fake", max_tokens=2048),
        model_name="fake-structured-model",
        pdf_download=PdfDownloadConfig(
            download_directory=root / "downloads",
            timeout_seconds=4,
            max_size_bytes=1024 * 1024,
            user_agent="PaperPilot-Test",
        ),
        export_directory=root / "exports",
        orchestrator_config=OrchestratorConfig(
            minimum_verification_score=minimum_score
        ),
    )


class BootstrapTests(unittest.TestCase):
    """Verify complete wiring, isolation, singleton reuse, and fake execution."""

    def test_container_is_created_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            factory = CapturingGraphFactory()
            container = create_application(
                make_config(Path(directory)),
                structured_llm=FakeStructuredLLM(),
                retrievers=[FakeRetriever()],
                graph_factory=factory,
            )

        self.assertIsInstance(container, ApplicationContainer)
        self.assertIs(container.application_service.graph, container.research_graph)
        self.assertIs(
            container.application_service.report_generator,
            container.report_service,
        )
        self.assertIs(
            container.application_service.export_service,
            container.export_service,
        )
        self.assertIs(container.application_service.task_store, container.task_store)

    def test_all_node_dependencies_are_injected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            llm = FakeStructuredLLM()
            factory = CapturingGraphFactory()
            container = create_application(
                make_config(Path(directory)),
                structured_llm=llm,
                retrievers=[FakeRetriever()],
                graph_factory=factory,
            )

        self.assertEqual(len(factory.calls), 1)
        planner, retriever, ingestion, reader, verifier, quality_gate = factory.calls[0]
        self.assertEqual(planner.name, "planner")
        self.assertIsNotNone(retriever.pipeline)
        self.assertIsNotNone(ingestion.pipeline)
        self.assertIs(reader.reader.llm, llm)
        self.assertIs(verifier.verifier.llm_verifier.llm, llm)
        self.assertIs(container.report_service.writer.llm, llm)
        self.assertEqual(
            quality_gate.config,
            container.config.orchestrator_config,
        )

    def test_default_llm_adapter_uses_non_secret_provider_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            factory = CapturingGraphFactory()
            create_application(
                make_config(Path(directory)),
                retrievers=[FakeRetriever()],
                graph_factory=factory,
            )

        llm = factory.calls[0][3].reader.llm
        self.assertEqual(llm.llm_provider, "fake")
        self.assertEqual(llm.model_name, "fake-structured-model")
        self.assertEqual(llm.max_tokens, 2048)

    def test_default_retrievers_include_unauthenticated_semantic_scholar(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"SEMANTIC_SCHOLAR_API_KEY": ""}, clear=False
        ):
            factory = CapturingGraphFactory()
            create_application(
                make_config(Path(directory)),
                structured_llm=FakeStructuredLLM(),
                graph_factory=factory,
            )

        retriever_node = factory.calls[0][1]
        self.assertEqual(
            [name for name, _ in retriever_node.pipeline._retrievers],
            ["arxiv", "semantic_scholar"],
        )

    def test_default_retrievers_enable_authenticated_semantic_scholar(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"SEMANTIC_SCHOLAR_API_KEY": "unit-test-key"}, clear=False
        ):
            factory = CapturingGraphFactory()
            create_application(
                make_config(Path(directory)),
                structured_llm=FakeStructuredLLM(),
                graph_factory=factory,
            )

        retriever_node = factory.calls[0][1]
        self.assertEqual(
            [name for name, _ in retriever_node.pipeline._retrievers],
            ["arxiv", "semantic_scholar"],
        )

    def test_application_service_runs_a_fake_complete_flow(self) -> None:
        question = "Analyze evidence-grounded visual SLAM research"
        analysis, document, verification, verified = make_verified_result()
        graph = FakeCompleteGraph(analysis, document, verification, verified)
        report = make_report(question, verified)
        with tempfile.TemporaryDirectory() as directory:
            container = create_application(
                make_config(Path(directory)),
                structured_llm=FakeStructuredLLM(report),
                retrievers=[FakeRetriever()],
                graph_factory=CapturingGraphFactory(graph),
            )

            result = container.application_service.run(
                ResearchRequest(
                    question=question,
                    max_papers=3,
                    export_format=ExportFormat.MARKDOWN,
                )
            )

            self.assertEqual(result.task.status, ResearchTaskStatus.COMPLETED)
            self.assertEqual(result.report.question, report.question)
            self.assertEqual(result.report.sections, report.sections)
            self.assertEqual(
                result.report.citations[0].paper_title,
                verified.original_analysis.paper_title,
            )
            self.assertTrue(Path(result.export_result.file_path).is_file())
            self.assertIsNotNone(result.export_result.artifact)

    def test_singleton_dependencies_are_not_recreated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = InMemoryTaskStore()
            llm = FakeStructuredLLM()
            factory = CapturingGraphFactory()
            container = create_application(
                make_config(Path(directory)),
                structured_llm=llm,
                retrievers=[FakeRetriever()],
                task_store=store,
                graph_factory=factory,
            )

        nodes = factory.calls[0]
        self.assertIs(container.task_store, store)
        self.assertIs(container.application_service.task_store, store)
        self.assertIs(nodes[3].reader.llm, nodes[4].verifier.llm_verifier.llm)
        self.assertIs(nodes[3].reader.llm, container.report_service.writer.llm)
        self.assertIs(
            container.export_service.verifier,
            container.export_service.markdown_exporter.verifier,
        )
        self.assertIs(
            container.export_service.verifier,
            container.export_service.html_exporter.verifier,
        )

    def test_configurations_are_isolated_between_containers(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            first_container = create_application(
                make_config(Path(first), minimum_score=0.5),
                structured_llm=FakeStructuredLLM(),
                retrievers=[FakeRetriever()],
                graph_factory=CapturingGraphFactory(),
            )
            second_container = create_application(
                make_config(Path(second), minimum_score=0.9),
                structured_llm=FakeStructuredLLM(),
                retrievers=[FakeRetriever()],
                graph_factory=CapturingGraphFactory(),
            )

        self.assertNotEqual(
            first_container.export_service.output_directory,
            second_container.export_service.output_directory,
        )
        self.assertEqual(
            first_container.config.orchestrator_config.minimum_verification_score,
            0.5,
        )
        self.assertEqual(
            second_container.config.orchestrator_config.minimum_verification_score,
            0.9,
        )

    def test_inputs_are_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory))
            original_config = config.model_copy(deep=True)
            retriever = FakeRetriever()
            retrievers = [retriever]
            llm = FakeStructuredLLM()

            container = create_application(
                config,
                structured_llm=llm,
                retrievers=retrievers,
                graph_factory=CapturingGraphFactory(),
            )

        self.assertEqual(config, original_config)
        self.assertIsNot(container.config, config)
        self.assertEqual(retrievers, [retriever])
        self.assertEqual(llm.calls, [])

    def test_plaintext_api_key_is_not_a_supported_config_field(self) -> None:
        with self.assertRaises(ValidationError):
            LLMProviderConfig(provider="fake", api_key="secret")


if __name__ == "__main__":
    unittest.main()
