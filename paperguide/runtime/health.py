"""Deterministic readiness checks for the PaperGuide runtime process."""

import importlib.util
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from paperguide.bootstrap import (
    ApplicationContainer,
    BootstrapConfig,
    create_application,
)

from .models import HealthCheckResult, HealthReport, HealthStatus
from .settings import RuntimeSettings

ApplicationFactory = Callable[[BootstrapConfig], ApplicationContainer]
ModuleFinder = Callable[[str], Any]


def check_runtime_health(
    settings: RuntimeSettings,
    *,
    application_factory: ApplicationFactory = create_application,
    module_finder: ModuleFinder = importlib.util.find_spec,
) -> HealthReport:
    """Check local prerequisites without network, LLM, or research execution."""

    safe_settings = RuntimeSettings.model_validate(settings.model_dump())
    checks = [
        _check_module(
            "langgraph",
            ("langgraph",),
            "LangGraph is available.",
            "LangGraph is unavailable.",
            module_finder,
        ),
        _check_module(
            "pdf_parser",
            ("fitz", "pymupdf"),
            "PDF parsing dependency is available.",
            "PyMuPDF is unavailable.",
            module_finder,
        ),
        _check_export_directory(safe_settings.export_directory),
        _check_bootstrap(safe_settings, application_factory),
    ]
    ready = all(check.status is HealthStatus.HEALTHY for check in checks)
    return HealthReport(
        status=HealthStatus.HEALTHY if ready else HealthStatus.UNHEALTHY,
        ready=ready,
        checks=checks,
    )


def _check_module(
    name: str,
    module_names: tuple[str, ...],
    success_message: str,
    failure_message: str,
    module_finder: ModuleFinder,
) -> HealthCheckResult:
    try:
        available = any(
            module_finder(module_name) is not None for module_name in module_names
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        available = False
    return HealthCheckResult(
        name=name,
        status=HealthStatus.HEALTHY if available else HealthStatus.UNHEALTHY,
        message=success_message if available else failure_message,
    )


def _check_export_directory(directory: Path) -> HealthCheckResult:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.is_dir():
            raise OSError("export target is not a directory")
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".health-", delete=True):
            pass
    except OSError:
        return HealthCheckResult(
            name="export_directory",
            status=HealthStatus.UNHEALTHY,
            message="Export directory is not writable.",
        )
    return HealthCheckResult(
        name="export_directory",
        status=HealthStatus.HEALTHY,
        message="Export directory is writable.",
    )


def _check_bootstrap(
    settings: RuntimeSettings,
    application_factory: ApplicationFactory,
) -> HealthCheckResult:
    try:
        container = application_factory(settings.to_bootstrap_config())
        if not callable(
            getattr(container.application_service, "run", None)
        ):
            raise TypeError("container has no application entry point")
    except Exception as error:
        return HealthCheckResult(
            name="bootstrap",
            status=HealthStatus.UNHEALTHY,
            message=f"Bootstrap failed ({type(error).__name__}).",
        )
    return HealthCheckResult(
        name="bootstrap",
        status=HealthStatus.HEALTHY,
        message="Application bootstrap succeeded.",
    )
