"""Offline end-to-end tests for the PaperGuide demonstration composition."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from paperguide.adapters import RetrieverProtocol
from paperguide.api.routes.tasks import task_response
from paperguide.application import ResearchRequest, ResearchTaskStatus
from paperguide.bootstrap import BootstrapConfig, LLMProviderConfig, PdfDownloadConfig
from paperguide.demo import (
    DEMO_QUESTION,
    FakeReader,
    FakeRetriever,
    FakeVerifier,
    create_demo_application,
    create_demo_seed,
)
from paperguide.execution import PersistentTaskStore
from paperguide.export import ExportFormat
from paperguide.runtime import RuntimeSettings, run_cli


def make_config(root: Path) -> BootstrapConfig:
    """Create isolated non-secret demo configuration."""

    return BootstrapConfig(
        llm_provider=LLMProviderConfig(provider="demo"),
        model_name="paperguide-offline-demo",
        pdf_download=PdfDownloadConfig(download_directory=root / "downloads"),
        export_directory=root / "artifacts",
    )


class DemoModeTests(unittest.TestCase):
    """Verify the complete demo remains offline, persistent, and exportable."""

    def test_fake_retriever_satisfies_protocol_and_returns_three_landmarks(self) -> None:
        retriever = FakeRetriever()

        papers = retriever.search(DEMO_QUESTION, max_results=3)

        self.assertIsInstance(retriever, RetrieverProtocol)
        self.assertEqual(len(papers), 3)
        self.assertEqual(
            [paper.publication_year for paper in papers],
            [1988, 2002, 2007],
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
            # The internal warning key is translated before export, so the
            # artifact carries the reader-facing disclaimer in its own language.
            exported = artifact.read_text("utf-8")
            self.assertTrue(
                "本报告使用版式测试数据" in exported
                or "layout-test data for preview only" in exported,
                "demo artifact must carry the synthetic-data disclaimer",
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
        settings = RuntimeSettings.from_env({"PAPERGUIDE_MODE": "DEMO"})
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

    def _demo_warnings(self, question: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            settings = RuntimeSettings(
                mode="production",
                model_name="unused",
                llm_provider="unused",
                export_directory=Path(directory) / "artifacts",
            )
            output = io.StringIO()
            run_cli(
                ["demo", "--question", question, "--max-papers", "5"],
                settings_loader=lambda: settings,
                stdout=output,
                stderr=io.StringIO(),
            )
            return list(json.loads(output.getvalue())["warnings"])

    def test_demo_says_so_when_the_question_is_outside_the_synthetic_corpus(self) -> None:
        """The corpus is a fixed SLAM set, and the narrative interpolates the
        question, so an unrelated question must not read as an answer to it."""

        unrelated = self._demo_warnings("分析屈服值预测相关的论文")
        self.assertTrue(
            any("与本次提问主题无关" in warning for warning in unrelated),
            unrelated,
        )

        # A question the corpus partly covers names only the missing term.
        partial = self._demo_warnings("YOLO与视觉SLAM融合研究进展")
        self.assertTrue(any("未覆盖提问中的 YOLO" in warning for warning in partial), partial)

        # A question the corpus covers carries no scope warning at all.
        covered = self._demo_warnings("视觉SLAM回环检测综述")
        self.assertFalse(
            any("演示语料" in warning for warning in covered),
            covered,
        )


if __name__ == "__main__":
    unittest.main()
