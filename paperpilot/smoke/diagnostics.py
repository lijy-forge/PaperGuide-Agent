"""Redaction, fingerprinting, and stage recording for smoke diagnostics."""

import hashlib
import re
from pathlib import Path

from paperpilot.orchestration.errors import sanitize_message

from .models import SmokeStage, SmokeStageStatus, StageDiagnostic, utc_now

_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\[^\s,;]+")
_UNIX_PATH_RE = re.compile(r"(?<!\w)/(?:[^\s/]+/)+[^\s,;]+")
_SENSITIVE_CONTENT_RE = re.compile(
    r"(?i)\b(?:prompt|full\s+pdf|paper\s+text|provider\s+response)\b\s*[:=].*"
)
_ENV_SECRET_RE = re.compile(
    r"(?i)\b[A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|SECRET)\s*[:=]\s*[^\s,;]+"
)
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def question_fingerprint(question: str) -> str:
    """Hash a normalized question without retaining its text."""

    normalized = " ".join(question.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def safe_diagnostic_message(message: object) -> str:
    """Redact credentials, absolute paths, and content-bearing diagnostic text."""

    value = _ENV_SECRET_RE.sub("[REDACTED]", str(message))
    value = sanitize_message(value)
    value = _WINDOWS_PATH_RE.sub("[LOCAL_PATH]", value)
    value = _UNIX_PATH_RE.sub("[LOCAL_PATH]", value)
    value = _SENSITIVE_CONTENT_RE.sub("[SENSITIVE_CONTENT_REDACTED]", value)
    return value[:300] or "operation failed"


def safe_error_code(error: BaseException) -> str:
    """Map an exception class to a stable non-sensitive diagnostic code."""

    name = type(error).__name__.upper()
    if "TIMEOUT" in name:
        return "TIMEOUT"
    if "PROVIDER" in name or "LLM" in name:
        return "PROVIDER_ERROR"
    if "PDF" in name:
        return "PDF_ERROR"
    if "EXPORT" in name or "ARTIFACT" in name:
        return "EXPORT_ERROR"
    if "NETWORK" in name or "CONNECTION" in name:
        return "NETWORK_ERROR"
    return "SMOKE_STAGE_FAILED"


def safe_artifact_filename(path: str | Path | None) -> str | None:
    """Return only a sanitized artifact basename."""

    if path is None:
        return None
    name = Path(path).name
    sanitized = _SAFE_FILENAME_RE.sub("-", name).lstrip(".")[:180]
    return sanitized or None


class StageRecorder:
    """Mutable internal recorder that emits immutable stage diagnostics."""

    def __init__(self) -> None:
        self._records = {
            stage: StageDiagnostic(stage=stage, status=SmokeStageStatus.PENDING)
            for stage in SmokeStage
        }

    def start(self, stage: SmokeStage) -> None:
        if self._records[stage].status is not SmokeStageStatus.PENDING:
            return
        self._records[stage] = StageDiagnostic(
            stage=stage,
            status=SmokeStageStatus.RUNNING,
            started_at=utc_now(),
        )

    def succeed(self, stage: SmokeStage, message: str | None = None) -> None:
        current = self._records[stage]
        if current.status in (
            SmokeStageStatus.SUCCEEDED,
            SmokeStageStatus.FAILED,
            SmokeStageStatus.SKIPPED,
        ):
            return
        started = current.started_at or utc_now()
        completed = utc_now()
        self._records[stage] = StageDiagnostic(
            stage=stage,
            status=SmokeStageStatus.SUCCEEDED,
            started_at=started,
            completed_at=completed,
            duration_ms=max(0.0, (completed - started).total_seconds() * 1000),
            safe_message=safe_diagnostic_message(message) if message else None,
        )

    def fail(
        self,
        stage: SmokeStage,
        error: BaseException,
        code: str | None = None,
    ) -> None:
        current = self._records[stage]
        if current.status in (SmokeStageStatus.FAILED, SmokeStageStatus.SKIPPED):
            return
        started = current.started_at or utc_now()
        completed = utc_now()
        self._records[stage] = StageDiagnostic(
            stage=stage,
            status=SmokeStageStatus.FAILED,
            started_at=started,
            completed_at=completed,
            duration_ms=max(0.0, (completed - started).total_seconds() * 1000),
            safe_error_code=code or safe_error_code(error),
            safe_message=safe_diagnostic_message(error),
        )

    def skip_pending(self, reason: str) -> None:
        for stage, record in tuple(self._records.items()):
            if record.status is SmokeStageStatus.PENDING:
                self._records[stage] = StageDiagnostic(
                    stage=stage,
                    status=SmokeStageStatus.SKIPPED,
                    safe_message=safe_diagnostic_message(reason),
                )

    def records(self) -> list[StageDiagnostic]:
        return [self._records[stage].model_copy(deep=True) for stage in SmokeStage]

    def status(self, stage: SmokeStage) -> SmokeStageStatus:
        """Return the current status without exposing mutable recorder state."""

        return self._records[stage].status
