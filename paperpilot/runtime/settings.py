"""Non-secret, environment-backed settings for the PaperPilot runtime."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paperpilot.bootstrap import (
    BootstrapConfig,
    LLMProviderConfig,
    PdfDownloadConfig,
)
from paperpilot.orchestration import OrchestratorConfig

from .exceptions import RuntimeConfigurationError

_ENV_PREFIX = "PAPERPILOT_"
_ENV_FIELDS = {
    "MODE": "mode",
    "MODEL_NAME": "model_name",
    "LLM_PROVIDER": "llm_provider",
    "EXPORT_DIRECTORY": "export_directory",
    "MAX_PAPERS": "max_papers",
    "LOG_LEVEL": "log_level",
    "ROUTE_CONFLICTS_TO_HUMAN_REVIEW": "route_conflicts_to_human_review",
}
_FORBIDDEN_SECRET_MARKERS = ("API_KEY", "TOKEN", "PASSWORD", "SECRET")
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_RUNTIME_MODES = {"production", "demo"}


class RuntimeSettings(BaseModel):
    """Validated runtime options containing no credentials or secret values."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    mode: str = "production"
    model_name: str = "gpt-5.4"
    llm_provider: str = "openai"
    export_directory: Path = Path("paperpilot-exports")
    max_papers: int = Field(default=10, ge=1, le=50)
    log_level: str = "INFO"
    route_conflicts_to_human_review: bool = False

    @field_validator("model_name", "llm_provider")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("runtime text settings must not be empty")
        return normalized

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in _RUNTIME_MODES:
            raise ValueError("runtime mode is unsupported")
        return normalized

    @field_validator("export_directory", mode="before")
    @classmethod
    def validate_export_directory(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            raise ValueError("export_directory must not be empty")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in _LOG_LEVELS:
            raise ValueError("log_level is unsupported")
        return normalized

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "RuntimeSettings":
        """Load only whitelisted ``PAPERPILOT_`` environment variables."""

        source = os.environ if environ is None else environ
        prefix_folded = _ENV_PREFIX.casefold()
        for name in source:
            folded = name.casefold()
            if not folded.startswith(prefix_folded):
                continue
            suffix = name[len(_ENV_PREFIX) :].upper()
            if any(marker in suffix for marker in _FORBIDDEN_SECRET_MARKERS):
                raise RuntimeConfigurationError(
                    f"secret-like runtime setting is forbidden: {_ENV_PREFIX}{suffix}"
                )

        values: dict[str, str] = {}
        casefolded = {name.casefold(): value for name, value in source.items()}
        for suffix, field_name in _ENV_FIELDS.items():
            environment_name = f"{_ENV_PREFIX}{suffix}".casefold()
            if environment_name in casefolded:
                values[field_name] = casefolded[environment_name]
        return cls.model_validate(values)

    def to_bootstrap_config(self) -> BootstrapConfig:
        """Create an isolated BootstrapConfig without adding credential fields."""

        export_directory = Path(self.export_directory)
        download_directory = export_directory.parent / "paperpilot-downloads"
        return BootstrapConfig(
            llm_provider=LLMProviderConfig(provider=self.llm_provider),
            model_name=self.model_name,
            pdf_download=PdfDownloadConfig(
                download_directory=download_directory,
            ),
            export_directory=export_directory,
            orchestrator_config=OrchestratorConfig(
                route_conflicts_to_human_review=(
                    self.route_conflicts_to_human_review
                )
            ),
        )

    def task_database_path(self) -> Path:
        """Return the deterministic local SQLite path shared by CLI and host."""

        return Path(self.export_directory).parent / "paperpilot-runtime.sqlite3"
