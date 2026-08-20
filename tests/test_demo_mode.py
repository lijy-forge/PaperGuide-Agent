"""Offline end-to-end tests for the PaperPilot demonstration composition."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from paperpilot.adapters import RetrieverProtocol
from paperpilot.api.routes.tasks import task_response
from paperpilot.application import ResearchRequest, ResearchTaskStatus
from paperpilot.bootstrap import BootstrapConfig, LLMProviderConfig, PdfDownloadConfig
from paperpilot.demo import (
    DEMO_QUESTION,
    FakeReader,
    FakeRetriever,
    FakeVerifier,
    create_demo_application,
    create_demo_seed,
)
from paperpilot.execution import PersistentTaskStore
from paperpilot.export import ExportFormat
from paperpilot.runtime import RuntimeSettings, run_cli


def make_config(root: Path) -> BootstrapConfig:
    """Create isolated non-secret demo configuration."""

    return BootstrapConfig(
        llm_provider=LLMProviderConfig(provider="demo"),
        model_name="paperpilot-offline-demo",
        pdf_download=PdfDownloadConfig(download_directory=root / "downloads"),
        export_directory=root / "artifacts",
    )


class DemoModeTests(unittest.TestCase):
    """Verify the complete demo remains offline, persistent, and exportable."""

    def test_fake_retriever_satisfies_protocol_and_returns_three_papers(self) -> None:
        retriever = FakeRetriever()

        papers = retriever.search(DEMO_QUESTION, max_results=3)

        self.assertIsInstance(retriever, RetrieverProtocol)
        self.assertEqual(len(papers), 3)
        self.assertEqual(
            [paper.publication_year for paper in papers],
            [2024, 2025, 2026],
        )

    def test_demo_does_not_require_credentials_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {}, clear=True
        ), patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            container = create_demo_application(make_config(Path(directory)))
            result = container.application_service.run(
                ResearchRequest(
                    question=DEMO_QUESTION,
                    max_papers=3,
                    export_format=ExportFormat.MARKDOWN,
                )
            )

        self.assertEqual(result.task.status, ResearchTaskStatus.COMPLETED)

    def test_complete_workflow_generates_grounded_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            container = create_demo_application(make_config(Path(directory)))

            result = container.application_service.run(
                ResearchRequest(question=DEMO_QUESTION, max_papers=3)
            )

            self.assertEqual(result.task.status, ResearchTaskStatus.COMPLETED)
            self.assertIsNotNone(result.report)
            # Demo now exercises the production Survey contract.  Its
            # reference and evidence data are carried by the Survey registry,
            # rather than the legacy ``ResearchReport.citations`` field.
            self.assertGreaterEqual(len(result.report.references), 1)
            self.assertGreaterEqual(len(result.report.evidence_appendix), 1)
            self.assertIsNotNone(result.task.artifact)
            artifact = Path(result.task.artifact.file_path)
            self.assertTrue(artifact.is_file())
            self.assertIn(
                "Offline demo uses synthetic papers",
                artifact.read_text("utf-8"),
            )

    def test_dashboard_status_contract_can_read_persisted_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = PersistentTaskStore(root / "runtime.sqlite3")
            container = create_demo_application(make_config(root), task_store=store)
            result = container.application_service.run(
                ResearchRequest(question=DEMO_QUESTION, max_papers=1)
            )

            response = task_response(store.get(result.task.task_id))

        self.assertEqual(response.status, ResearchTaskStatus.COMPLETED)
        self.assertTrue(response.artifact_available)
        self.assertEqual(response.artifact_format, ExportFormat.MARKDOWN)

    def test_fake_reader_and_verifier_leave_seed_document_unchanged(self) -> None:
        seed = create_demo_seed()
        document = seed.documents[0].model_copy(deep=True)
        original = document.model_copy(deep=True)

        analysis = FakeReader().analyze(document)
        verification = FakeVerifier().verify(analysis, document)

        self.assertEqual(document, original)
        self.assertEqual(verification.total_verified, 2)
        self.assertEqual(verification.rejected_evidence_ids, [])

    def test_runtime_mode_defaults_to_production_and_loads_demo(self) -> None:
        self.assertEqual(RuntimeSettings().mode, "production")
        settings = RuntimeSettings.from_env({"PAPERPILOT_MODE": "DEMO"})
        self.assertEqual(settings.mode, "demo")

    def test_demo_cli_runs_complete_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = RuntimeSettings(
                mode="production",
                model_name="unused",
                llm_provider="unused",
                export_directory=Path(directory) / "artifacts",
            )
            output = io.StringIO()
            errors = io.StringIO()

            exit_code = run_cli(
                ["demo"],
                settings_loader=lambda: settings,
                stdout=output,
                stderr=errors,
            )

            payload = json.loads(output.getvalue())
            database = settings.task_database_path()
            saved = PersistentTaskStore(database).get(UUID(payload["task_id"]))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "demo")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(saved.status, ResearchTaskStatus.COMPLETED)
        self.assertEqual(errors.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
