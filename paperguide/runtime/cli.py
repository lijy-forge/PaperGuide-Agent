"""Standard-library command-line entry point for PaperGuide research runs."""

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO
from uuid import UUID, uuid4

from paperguide.application import ResearchRequest, ResearchTask, ResearchTaskStatus
from paperguide.bootstrap import (
    ApplicationContainer,
    BootstrapConfig,
    create_application,
)
from paperguide.execution import PersistentTaskStore, TaskExecutorProtocol
from paperguide.export import ExportFormat

from .env_file import load_env_file
from .health import check_runtime_health
from .host import (
    TaskHost,
    TaskHostUnavailableError,
    create_task_host_client,
)
from .models import HealthReport
from .settings import RuntimeSettings

LOGGER = logging.getLogger("paperguide.runtime")
SettingsLoader = Callable[[], RuntimeSettings]
ApplicationFactory = Callable[[BootstrapConfig], ApplicationContainer]
HealthChecker = Callable[[RuntimeSettings], HealthReport]
SleepFunction = Callable[[float], None]
MonotonicFunction = Callable[[], float]
TaskHostFactory = Callable[[RuntimeSettings], TaskHost]

_WAIT_TERMINAL_STATUSES = {
    ResearchTaskStatus.COMPLETED,
    ResearchTaskStatus.FAILED,
    ResearchTaskStatus.HUMAN_REVIEW,
    ResearchTaskStatus.CANCELLED,
    ResearchTaskStatus.DEAD_LETTER,
}


def build_parser() -> argparse.ArgumentParser:
    """Build the stable public CLI parser."""

    parser = argparse.ArgumentParser(prog="paperguide")
    commands = parser.add_subparsers(dest="command", required=True)

    research = commands.add_parser("research", help="run or submit research")
    research.add_argument(
        "action_or_question",
        help="technical question, or 'submit' for background execution",
    )
    research.add_argument(
        "submitted_question",
        nargs="?",
        help="technical question for the submit command",
    )
    research.add_argument("--max-papers", type=int, default=None)
    research.add_argument(
        "--format",
        dest="export_format",
        choices=[item.value for item in ExportFormat],
        default=ExportFormat.MARKDOWN.value,
    )

    task = commands.add_parser("task", help="inspect background tasks")
    task_commands = task.add_subparsers(dest="task_command", required=True)
    status = task_commands.add_parser("status", help="get current task status")
    status.add_argument("task_id")
    wait = task_commands.add_parser("wait", help="wait for a terminal task status")
    wait.add_argument("task_id")
    wait.add_argument("--poll-interval", type=float, default=0.25)
    wait.add_argument("--timeout", type=float, default=300.0)
    cancel = task_commands.add_parser("cancel", help="request task cancellation")
    cancel.add_argument("task_id")
    server = commands.add_parser("server", help="manage the persistent task host")
    server_commands = server.add_subparsers(dest="server_command", required=True)
    server_commands.add_parser("start", help="start the persistent task host")
    commands.add_parser("health", help="check local runtime prerequisites")
    demo = commands.add_parser("demo", help="run the offline PaperGuide demo")
    demo.add_argument(
        "--question",
        default=None,
        help="optional demo question; synthetic evidence remains fixed",
    )
    demo.add_argument("--max-papers", type=int, default=15)
    demo.add_argument(
        "--format",
        dest="export_format",
        choices=[item.value for item in ExportFormat],
        default=ExportFormat.MARKDOWN.value,
    )
    return parser


def configure_logging(level: str) -> None:
    """Configure standard logging without including user input or settings values."""

    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: SettingsLoader = RuntimeSettings.from_env,
    application_factory: ApplicationFactory = create_application,
    health_checker: HealthChecker = check_runtime_health,
    task_executor: TaskExecutorProtocol | None = None,
    task_host_factory: TaskHostFactory = TaskHost,
    sleep_fn: SleepFunction = time.sleep,
    monotonic_fn: MonotonicFunction = time.monotonic,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute a CLI command using dependency-injected runtime boundaries."""

    output = stdout or sys.stdout
    error_output = stderr or sys.stderr
    arguments = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        # Before the settings are read, or a key written to .env is ignored
        # with no error and the run behaves as if nothing was configured.
        load_env_file()
        settings = settings_loader()
        configure_logging(settings.log_level)
        if arguments.command == "health":
            report = health_checker(settings)
            _write_json(output, report.model_dump(mode="json"))
            return 0 if report.ready else 1

        if arguments.command == "server":
            if settings.mode == "demo" and task_host_factory is TaskHost:
                from paperguide.demo import create_demo_application

                host = TaskHost(
                    settings,
                    application_factory=create_demo_application,
                )
            else:
                host = task_host_factory(settings)
            LOGGER.info("persistent task host starting")
            try:
                host.serve_forever()
            except KeyboardInterrupt:
                host.shutdown()
                return 130
            return 0

        if arguments.command == "task":
            executor = _resolve_task_executor(
                task_executor,
                settings,
            )
            task_id = UUID(arguments.task_id)
            if arguments.task_command == "status":
                _write_json(output, _task_payload(executor.get_status(task_id)))
                return 0
            if arguments.task_command == "cancel":
                _write_json(output, _task_payload(executor.cancel(task_id)))
                return 0
            if arguments.poll_interval < 0 or arguments.timeout < 0:
                raise ValueError("wait timing values must not be negative")
            task = _wait_for_task(
                executor,
                task_id,
                poll_interval=arguments.poll_interval,
                timeout=arguments.timeout,
                sleep_fn=sleep_fn,
                monotonic_fn=monotonic_fn,
            )
            _write_json(output, _task_payload(task))
            return 0

        demo_command = arguments.command == "demo"
        if demo_command:
            from paperguide.demo import DEMO_QUESTION

            question = arguments.question or DEMO_QUESTION
            max_papers = arguments.max_papers
            submit_mode = False
        else:
            max_papers = (
                settings.max_papers
                if arguments.max_papers is None
                else arguments.max_papers
            )
            submit_mode = arguments.action_or_question == "submit"
            question = (
                arguments.submitted_question
                if submit_mode
                else arguments.action_or_question
            )
        if not question:
            raise ValueError("research question is required")
        if (
            not demo_command
            and not submit_mode
            and arguments.submitted_question is not None
        ):
            raise ValueError("unexpected additional research argument")
        request = ResearchRequest(
            question=question,
            max_papers=max_papers,
            export_format=ExportFormat(arguments.export_format),
        )
        if submit_mode:
            executor = _resolve_task_executor(
                task_executor,
                settings,
            )
            handle = executor.submit(request)
            _write_json(
                output,
                {
                    "task_id": str(handle.task_id),
                    "status": handle.status.value,
                },
            )
            return 0

        if demo_command or settings.mode == "demo":
            from paperguide.demo import create_demo_application

            demo_config = settings.to_bootstrap_config().model_copy(
                update={
                    "export_directory": (
                        Path(settings.export_directory) / "demo" / str(uuid4())
                    )
                },
                deep=True,
            )
            container = create_demo_application(
                demo_config,
                task_store=PersistentTaskStore(settings.task_database_path()),
            )
        else:
            container = application_factory(settings.to_bootstrap_config())
        result = container.application_service.run(request)
        warnings = []
        if result.report is not None:
            warnings.extend(result.report.warnings)
        if result.export_result is not None:
            warnings.extend(result.export_result.warnings)
        artifact = result.task.artifact
        _write_json(
            output,
            {
                "task_id": str(result.task.task_id),
                "status": result.task.status.value,
                "artifact": (
                    _safe_artifact_path(artifact.file_path)
                    if artifact is not None
                    else None
                ),
                "warnings": list(dict.fromkeys(warnings)),
                "mode": (
                    "demo"
                    if demo_command or settings.mode == "demo"
                    else "production"
                ),
            },
        )
        LOGGER.info("research task finished with status %s", result.task.status.value)
        return 0
    except TaskHostUnavailableError:
        LOGGER.error("persistent task host is unavailable")
        _write_json(
            error_output,
            {
                "status": "failed",
                "error": "task host is unavailable; run 'paperguide server start'",
            },
        )
        return 1
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        LOGGER.error("runtime command failed (%s)", type(error).__name__)
        _write_json(
            error_output,
            {
                "status": "failed",
                "error": f"runtime command failed ({type(error).__name__})",
            },
        )
        return 1


def _wait_for_task(
    executor: TaskExecutorProtocol,
    task_id: UUID,
    *,
    poll_interval: float,
    timeout: float,
    sleep_fn: SleepFunction,
    monotonic_fn: MonotonicFunction,
) -> ResearchTask:
    deadline = monotonic_fn() + timeout
    while True:
        task = executor.get_status(task_id)
        if task.status in _WAIT_TERMINAL_STATUSES:
            return task
        if monotonic_fn() >= deadline:
            raise TimeoutError("task wait timed out")
        sleep_fn(poll_interval)


def _resolve_task_executor(
    task_executor: TaskExecutorProtocol | None,
    settings: RuntimeSettings,
) -> TaskExecutorProtocol:
    if task_executor is not None:
        return task_executor
    return create_task_host_client(settings)


def _task_payload(task: ResearchTask) -> dict[str, object]:
    artifact = task.artifact
    return {
        "task_id": str(task.task_id),
        "status": task.status.value,
        "artifact": (
            _safe_artifact_path(artifact.file_path) if artifact is not None else None
        ),
        "error": (
            "task execution failed"
            if task.status is ResearchTaskStatus.FAILED
            else None
        ),
    }


def _safe_artifact_path(file_path: str) -> str:
    """Return only the artifact basename so host filesystem paths stay private."""

    return Path(file_path).name


def _write_json(stream: TextIO, payload: object) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    stream.write("\n")


def main() -> None:
    """Installed console-script entry point."""

    raise SystemExit(run_cli())
