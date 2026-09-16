"""Manual, real end-to-end validation for PaperGuide."""

from .config import SmokeTestConfig, real_e2e_enabled
from .diagnostics import StageRecorder, question_fingerprint, safe_diagnostic_message
from .models import (
    SmokeStage,
    SmokeStageStatus,
    SmokeTestResult,
    SmokeTestStatus,
    StageDiagnostic,
)
from .runner import (
    ProviderNotConfiguredError,
    SmokeApplicationProtocol,
    SmokeTestRunner,
    check_provider_configuration,
    create_real_smoke_application,
)

__all__ = [
    "ProviderNotConfiguredError",
    "SmokeApplicationProtocol",
    "SmokeStage",
    "SmokeStageStatus",
    "SmokeTestConfig",
    "SmokeTestResult",
    "SmokeTestRunner",
    "SmokeTestStatus",
    "StageDiagnostic",
    "StageRecorder",
    "check_provider_configuration",
    "create_real_smoke_application",
    "question_fingerprint",
    "real_e2e_enabled",
    "safe_diagnostic_message",
]
