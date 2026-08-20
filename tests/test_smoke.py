"""Offline tests for safe, injectable end-to-end smoke diagnostics."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from paperpilot.application import ResearchResult, ResearchTask, ResearchTaskStatus
from paperpilot.domain import PaperSource, SourceLocator
from paperpilot.export import ArtifactMetadata, ExportFormat, ExportResult
from paperpilot.reporting import (
    ReportCitation,
    ReportClaim,
    ReportSection,
    ResearchReport,
)
from paperpilot.smoke import (
    ProviderNotConfiguredError,
    SmokeStage,
    SmokeStageStatus,
    SmokeTestConfig,
    SmokeTestRunner,
    SmokeTestStatus,
    StageRecorder,
    check_provider_configuration,
    question_fingerprint,
    real_e2e_enabled,
    safe_diagnostic_message,
)
from paperpilot.smoke.diagnostics import safe_artifact_filename


def make_completed_result(question: str) -> ResearchResult:
    paper_id = uuid4()
    evidence_id = uuid4()
    report = ResearchReport(
        question=question,
        title="Safe smoke report",
        summary="One verified finding.",
        sections=[
            ReportSection(
                title="Finding",
                claims=[
                    ReportClaim(
                        text="A supported claim.",
                        evidence_ids=[evidence_id],
                    )
                ],
                evidence_ids=[evidence_id],
            )
        ],
        citations=[
            ReportCitation(
                paper_id=paper_id,
                evidence_id=evidence_id,
                quote="A short verified quote.",
                locator=SourceLocator(paper_id=paper_id, page_start=1, page_end=1),
            )
        ],
        evidence_ids=[evidence_id],
        warnings=[],
    )
    payload = b"report"
    artifact = ArtifactMetadata(
        format=ExportFormat.MARKDOWN,
        file_path=str(Path("artifact.md").resolve()),
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    export = ExportResult(
        format=ExportFormat.MARKDOWN,
        media_type="text/markdown",
        content=payload.decode(),
        file_path=artifact.file_path,
        size_bytes=len(payload),
        warnings=[],
        artifact=artifact,
    )
    task = ResearchTask(
        run_id=uuid4(),
        question=question,
        status=ResearchTaskStatus.COMPLETED,
        artifact=artifact,
    )
    return ResearchResult(task=task, report=report, export_result=export)


class FakeApplication:
    def __init__(self, result: ResearchResult) -> None:
        self.result = result
        self.requests = []

    def run(self, request):
        self.requests.append(request.model_copy(deep=True))
        return self.result.model_copy(deep=True)


class SmokeTests(unittest.TestCase):
    def test_config_defaults_are_cost_bounded(self) -> None:
        config = SmokeTestConfig()
        self.assertEqual(config.max_papers, 1)
        self.assertEqual(config.sources, [PaperSource.ARXIV])
        self.assertEqual(config.export_format, ExportFormat.MARKDOWN)

    def test_config_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValidationError):
            SmokeTestConfig(question=" ", max_papers=4)

    def test_question_fingerprint_is_safe_and_stable(self) -> None:
        question = "Confidential Research Question"
        fingerprint = question_fingerprint(question)
        self.assertEqual(fingerprint, question_fingerprint(question.upper()))
        self.assertEqual(len(fingerprint), 64)
        self.assertNotIn("confidential", fingerprint)

    def test_stage_recorder_records_timing(self) -> None:
        recorder = StageRecorder()
        recorder.start(SmokeStage.PDF_PARSE)
        recorder.succeed(SmokeStage.PDF_PARSE, "parsed")
        stage = next(
            item for item in recorder.records() if item.stage is SmokeStage.PDF_PARSE
        )
        self.assertEqual(stage.stage, SmokeStage.PDF_PARSE)
        self.assertEqual(stage.status, SmokeStageStatus.SUCCEEDED)
        self.assertIsNotNone(stage.duration_ms)

    def test_failure_diagnostic_redacts_secret_and_path(self) -> None:
        message = safe_diagnostic_message(
            r"OPENAI_API_KEY=sk-example at C:\Users\person\secret\file.txt"
        )
        self.assertNotIn("sk-example", message)
        self.assertNotIn("C:\\Users", message)

    def test_provider_not_configured_is_explicit(self) -> None:
        with self.assertRaises(ProviderNotConfiguredError):
            check_provider_configuration("openai", {})
        check_provider_configuration("openai", {"OPENAI_API_KEY": "present"})

    def test_artifact_filename_discards_path(self) -> None:
        self.assertEqual(safe_artifact_filename("../../private/report.md"), "report.md")

    def test_real_e2e_switch_defaults_off(self) -> None:
        self.assertFalse(real_e2e_enabled({}))
        self.assertTrue(real_e2e_enabled({"PAPERPILOT_RUN_REAL_E2E": "1"}))

    def test_runner_accepts_fake_application_and_writes_safe_json(self) -> None:
        question = "Do not persist this exact question"
        fake = FakeApplication(make_completed_result(question))

        def factory(config, recorder):
            return fake, lambda: None

        with tempfile.TemporaryDirectory() as directory:
            config = SmokeTestConfig(
                question=question,
                output_directory=Path(directory),
            )
            original = copy.deepcopy(config)
            result = SmokeTestRunner(factory).run(config)
            payload = (Path(directory) / "smoke-result.json").read_text("utf-8")

        self.assertEqual(result.status, SmokeTestStatus.PASSED)
        self.assertEqual(config, original)
        self.assertEqual(len(fake.requests), 1)
        self.assertNotIn(question, payload)
        self.assertEqual(json.loads(payload)["artifact_filename"], "artifact.md")

    def test_failed_stage_is_never_reported_as_success(self) -> None:
        def failing_factory(config, recorder):
            raise ProviderNotConfiguredError("provider credential missing")

        with tempfile.TemporaryDirectory() as directory:
            result = SmokeTestRunner(failing_factory).run(
                SmokeTestConfig(output_directory=Path(directory))
            )

        provider = next(
            item for item in result.stages
            if item.stage is SmokeStage.PROVIDER_INITIALIZATION
        )
        self.assertEqual(result.status, SmokeTestStatus.FAILED)
        self.assertEqual(provider.status, SmokeStageStatus.FAILED)
        self.assertFalse(result.report_generated)


if __name__ == "__main__":
    unittest.main()
