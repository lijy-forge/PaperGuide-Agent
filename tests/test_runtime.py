"""Unit tests for runtime settings, readiness checks, and CLI entry."""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from pydantic import ValidationError

from paperpilot.application import ResearchTaskStatus
from paperpilot.export import ExportFormat
from paperpilot.runtime import (
    HealthStatus,
    RuntimeConfigurationError,
    RuntimeSettings,
    check_runtime_health,
    run_cli,
)


class FakeApplicationService:
    """Return a completed task without Graph, LLM, network, or file access."""

    def __init__(self):
        self.requests = []

    def run(self, request):
        self.requests.append(request.model_copy(deep=True))
        artifact = SimpleNamespace(
            file_path=str(Path("private/root/research-report.md").resolve())
        )
        task = SimpleNamespace(
            task_id=uuid4(),
            status=ResearchTaskStatus.COMPLETED,
            artifact=artifact,
        )
        return SimpleNamespace(
            task=task,
            report=SimpleNamespace(warnings=["report warning"]),
            export_result=SimpleNamespace(
                warnings=["export warning", "report warning"]
            ),
        )


class FakeApplicationFactory:
    """Capture BootstrapConfig and return one reusable fake application."""

    def __init__(self, service=None, error=None):
        self.service = service or FakeApplicationService()
        self.error = error
        self.configs = []

    def __call__(self, config):
        self.configs.append(config.model_copy(deep=True))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(application_service=self.service)


def make_settings(root: Path) -> RuntimeSettings:
    """Create isolated runtime settings for one test."""

    return RuntimeSettings(
        model_name="fake-model",
        llm_provider="fake-provider",
        export_directory=root / "exports",
        max_papers=7,
        log_level="warning",
    )


class RuntimeTests(unittest.TestCase):
    """Verify safe configuration, health reports, CLI output, and isolation."""

    def test_environment_variables_are_loaded(self) -> None:
        environment = {
            "PAPERPILOT_MODEL_NAME": "research-model",
            "PAPERPILOT_LLM_PROVIDER": "local-provider",
            "PAPERPILOT_EXPORT_DIRECTORY": "artifacts",
            "PAPERPILOT_MAX_PAPERS": "12",
            "PAPERPILOT_LOG_LEVEL": "debug",
            "PAPERPILOT_ROUTE_CONFLICTS_TO_HUMAN_REVIEW": "true",
            "UNRELATED_VALUE": "ignored",
        }
        original = dict(environment)

        settings = RuntimeSettings.from_env(environment)

        self.assertEqual(settings.model_name, "research-model")
        self.assertEqual(settings.llm_provider, "local-provider")
        self.assertEqual(settings.export_directory, Path("artifacts"))
        self.assertEqual(settings.max_papers, 12)
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertTrue(settings.route_conflicts_to_human_review)
        self.assertTrue(
            settings.to_bootstrap_config()
            .orchestrator_config.route_conflicts_to_human_review
        )
        self.assertEqual(environment, original)

    def test_local_runtime_degrades_safely_when_conflicts_exist(self) -> None:
        settings = RuntimeSettings()

        self.assertFalse(settings.route_conflicts_to_human_review)
        self.assertFalse(
            settings.to_bootstrap_config()
            .orchestrator_config.route_conflicts_to_human_review
        )

    def test_invalid_and_unknown_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RuntimeSettings(max_papers=0)
        with self.assertRaises(ValidationError):
            RuntimeSettings(api_key="not-allowed")
        with self.assertRaises(ValidationError):
            RuntimeSettings(log_level="verbose")

    def test_health_check_reports_all_prerequisites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            original = settings.model_copy(deep=True)
            factory = FakeApplicationFactory()

            report = check_runtime_health(
                settings,
                application_factory=factory,
                module_finder=lambda name: object(),
            )

        self.assertTrue(report.ready)
        self.assertEqual(report.status, HealthStatus.HEALTHY)
        self.assertEqual(
            [check.name for check in report.checks],
            ["langgraph", "pdf_parser", "export_directory", "bootstrap"],
        )
        self.assertEqual(settings, original)
        self.assertEqual(len(factory.configs), 1)

    def test_health_check_is_unhealthy_when_dependency_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = check_runtime_health(
                make_settings(Path(directory)),
                application_factory=FakeApplicationFactory(),
                module_finder=lambda name: None if name == "langgraph" else object(),
            )

        self.assertFalse(report.ready)
        self.assertEqual(report.status, HealthStatus.UNHEALTHY)
        self.assertEqual(report.checks[0].status, HealthStatus.UNHEALTHY)

    def test_cli_runs_fake_application(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            service = FakeApplicationService()
            factory = FakeApplicationFactory(service)
            output = io.StringIO()
            errors = io.StringIO()

            exit_code = run_cli(
                ["research", "Analyze visual SLAM", "--format", "markdown"],
                settings_loader=lambda: settings,
                application_factory=factory,
                stdout=output,
                stderr=errors,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifact"], "research-report.md")
        self.assertEqual(payload["warnings"], ["report warning", "export warning"])
        self.assertEqual(service.requests[0].question, "Analyze visual SLAM")
        self.assertEqual(service.requests[0].max_papers, 7)
        self.assertEqual(service.requests[0].export_format, ExportFormat.MARKDOWN)
        self.assertEqual(errors.getvalue(), "")

    def test_cli_health_command_outputs_structured_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            report = check_runtime_health(
                settings,
                application_factory=FakeApplicationFactory(),
                module_finder=lambda name: object(),
            )
            output = io.StringIO()

            exit_code = run_cli(
                ["health"],
                settings_loader=lambda: settings,
                health_checker=lambda current: report,
                stdout=output,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ready"])
        self.assertEqual(len(payload["checks"]), 4)

    def test_secret_environment_value_is_never_exposed(self) -> None:
        secret = "do-not-leak-this-value"
        environment = {"PAPERPILOT_API_KEY": secret}

        with self.assertRaises(RuntimeConfigurationError) as captured:
            RuntimeSettings.from_env(environment)

        self.assertNotIn(secret, str(captured.exception))

        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            errors = io.StringIO()
            exit_code = run_cli(
                ["research", "Question"],
                settings_loader=lambda: make_settings(Path(directory)),
                application_factory=FakeApplicationFactory(
                    error=RuntimeError(secret)
                ),
                stdout=output,
                stderr=errors,
            )
        self.assertEqual(exit_code, 1)
        self.assertNotIn(secret, errors.getvalue())
        self.assertNotIn(secret, output.getvalue())

    def test_cli_and_settings_inputs_are_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            original_settings = settings.model_copy(deep=True)
            arguments = ["research", "Question", "--max-papers", "4"]
            original_arguments = list(arguments)
            service = FakeApplicationService()

            exit_code = run_cli(
                arguments,
                settings_loader=lambda: settings,
                application_factory=FakeApplicationFactory(service),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(settings, original_settings)
        self.assertEqual(arguments, original_arguments)
        self.assertEqual(service.requests[0].max_papers, 4)


if __name__ == "__main__":
    unittest.main()
