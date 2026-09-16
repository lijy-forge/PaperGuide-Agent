"""Safe, explicit provider connectivity checks executed by the TaskHost."""

from __future__ import annotations

import os
import time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from paperguide.analysis import StructuredLLMProtocol


class ProviderPreflightStatus(str, Enum):
    """Terminal status of one explicit provider preflight."""

    PASS = "pass"
    FAIL = "fail"


class ProviderFailureCategory(str, Enum):
    """Safe failure categories; raw provider messages never leave the host."""

    NONE = "none"
    PROVIDER_AUTH = "provider_auth"
    PROVIDER_BILLING = "provider_billing"
    PROVIDER_CONNECTION = "provider_connection"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_SERVER_ERROR = "provider_server_error"
    UNKNOWN = "unknown"


class ProviderPreflightResult(BaseModel):
    """Sanitized result of one minimal provider call from the Host context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ProviderPreflightStatus
    credential_present: bool
    provider: str
    model: str
    elapsed_ms: float = Field(ge=0.0)
    failure_category: ProviderFailureCategory
    safe_exception_class: str | None = None


class _ProbeResponse(BaseModel):
    """Minimal schema used solely to exercise the production structured adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: Literal["ok"]


_CREDENTIAL_ENVIRONMENT_NAMES: dict[str, tuple[str, ...]] = {
    "deepseek": ("DEEPSEEK_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "azure_openai": ("AZURE_OPENAI_API_KEY",),
}


class HostProviderPreflight:
    """Run exactly one small structured call through the production LLM adapter."""

    def __init__(
        self,
        llm: StructuredLLMProtocol,
        *,
        provider: str,
        model: str,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._llm = llm
        self.provider = provider.strip()
        self.model = model.strip()
        self._environ = environ

    def run(self) -> ProviderPreflightResult:
        """Check credential inheritance then make one small provider request."""

        started = time.monotonic()
        credential_present = self._credential_present()
        if not credential_present:
            return self._result(
                ProviderPreflightStatus.FAIL,
                credential_present=False,
                elapsed_ms=self._elapsed_ms(started),
                category=ProviderFailureCategory.PROVIDER_AUTH,
                exception_class="CredentialMissing",
            )
        try:
            self._llm.generate_structured(
                system_prompt=(
                    "You are a provider connectivity probe. Return only the required JSON."
                ),
                user_prompt='Return {"ok":"ok"}.',
                response_model=_ProbeResponse,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as error:
            category = _classify_failure(error)
            return self._result(
                ProviderPreflightStatus.FAIL,
                credential_present=True,
                elapsed_ms=self._elapsed_ms(started),
                category=category,
                exception_class=_safe_exception_class(category),
            )
        return self._result(
            ProviderPreflightStatus.PASS,
            credential_present=True,
            elapsed_ms=self._elapsed_ms(started),
            category=ProviderFailureCategory.NONE,
            exception_class=None,
        )

    def _credential_present(self) -> bool:
        environment = os.environ if self._environ is None else self._environ
        names = _CREDENTIAL_ENVIRONMENT_NAMES.get(
            self.provider.casefold(),
            (),
        )
        return any(environment.get(name, "").strip() for name in names)

    def _result(
        self,
        status: ProviderPreflightStatus,
        *,
        credential_present: bool,
        elapsed_ms: float,
        category: ProviderFailureCategory,
        exception_class: str | None,
    ) -> ProviderPreflightResult:
        return ProviderPreflightResult(
            status=status,
            credential_present=credential_present,
            provider=self.provider,
            model=self.model,
            elapsed_ms=elapsed_ms,
            failure_category=category,
            safe_exception_class=exception_class,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return max(0.0, (time.monotonic() - started) * 1000)


def _classify_failure(error: Exception) -> ProviderFailureCategory:
    """Classify exception metadata locally without returning its message/body."""

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status_code = getattr(current, "status_code", None)
        if status_code == 402:
            return ProviderFailureCategory.PROVIDER_BILLING
        if status_code in (401, 403):
            return ProviderFailureCategory.PROVIDER_AUTH
        if status_code == 429:
            return ProviderFailureCategory.PROVIDER_RATE_LIMIT
        if isinstance(status_code, int) and 500 <= status_code <= 599:
            return ProviderFailureCategory.PROVIDER_SERVER_ERROR
        name = type(current).__name__.casefold()
        message = str(current).casefold()
        if "timeout" in name or "timeout" in message:
            return ProviderFailureCategory.PROVIDER_TIMEOUT
        if "rate" in name or "429" in message or "rate limit" in message:
            return ProviderFailureCategory.PROVIDER_RATE_LIMIT
        if "auth" in name or "forbidden" in name or "401" in message or "403" in message:
            return ProviderFailureCategory.PROVIDER_AUTH
        if "billing" in name or "402" in message or "payment" in message:
            return ProviderFailureCategory.PROVIDER_BILLING
        if "connection" in name or "connect" in name or "network" in name:
            return ProviderFailureCategory.PROVIDER_CONNECTION
        if "server" in name or "service" in name:
            return ProviderFailureCategory.PROVIDER_SERVER_ERROR
        current = current.__cause__ or current.__context__
    return ProviderFailureCategory.UNKNOWN


def _safe_exception_class(category: ProviderFailureCategory) -> str:
    """Return a stable category label instead of a raw exception type/message."""

    labels = {
        ProviderFailureCategory.PROVIDER_AUTH: "ProviderAuthError",
        ProviderFailureCategory.PROVIDER_BILLING: "ProviderBillingError",
        ProviderFailureCategory.PROVIDER_CONNECTION: "ProviderConnectionError",
        ProviderFailureCategory.PROVIDER_TIMEOUT: "ProviderTimeoutError",
        ProviderFailureCategory.PROVIDER_RATE_LIMIT: "ProviderRateLimitError",
        ProviderFailureCategory.PROVIDER_SERVER_ERROR: "ProviderServerError",
        ProviderFailureCategory.UNKNOWN: "ProviderUnknownError",
    }
    return labels.get(category, "ProviderPreflightError")
