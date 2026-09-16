"""Immutable configuration contracts for the PaperGuide composition root."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paperguide.orchestration import OrchestratorConfig


class LLMProviderConfig(BaseModel):
    """Non-secret settings used to construct the structured LLM adapter.

    Credentials intentionally are not part of this model. Providers must obtain
    credentials through their normal environment or workload-identity mechanism.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    max_tokens: int = Field(default=12_000, ge=256, le=1_000_000)
    request_timeout_seconds: float = Field(default=180.0, gt=0.0, le=600.0)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("LLM provider must not be empty")
        return normalized


class PdfDownloadConfig(BaseModel):
    """Filesystem and network limits for PDF acquisition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    download_directory: Path
    timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    user_agent: str = "PaperGuide"

    @field_validator("user_agent")
    @classmethod
    def validate_user_agent(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("PDF user_agent must not be empty")
        return normalized


class BootstrapConfig(BaseModel):
    """Complete non-secret configuration for one isolated application container."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    llm_provider: LLMProviderConfig
    model_name: str
    pdf_download: PdfDownloadConfig
    export_directory: Path
    orchestrator_config: OrchestratorConfig = Field(
        default_factory=OrchestratorConfig
    )
    report_max_context_chars: int = Field(default=30_000, ge=1)

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model_name must not be empty")
        return normalized
