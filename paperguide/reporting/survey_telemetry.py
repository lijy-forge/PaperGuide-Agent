"""Private, content-free telemetry for production survey synthesis diagnostics."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from pydantic import ValidationError

from paperguide.analysis.exceptions import (
    AnalysisLLMResponseError,
    AnalysisSchemaValidationError,
)
from paperguide.progress.events import TaskEventType

from .exceptions import ReportSchemaValidationError


class SurveyTelemetryProtocol(Protocol):
    """Best-effort private observer that must not affect survey behavior."""

    def stage_started(self) -> None: ...
    def stage_completed(self) -> None: ...
    def stage_aborted(self, error: Exception) -> None: ...
    def substage_started(self, substage: str) -> float: ...
    def substage_completed(self, substage: str, started: float) -> None: ...
    def substage_failed(self, substage: str, started: float, error: Exception) -> None: ...
    def llm_started(self, substage: str, call_index: int, estimated_input_chars: int) -> float: ...
    def llm_succeeded(self, substage: str, call_index: int, started: float) -> None: ...
    def llm_failed(self, substage: str, call_index: int, started: float, error: Exception) -> None: ...
    def update_input_counts(self, **counts: int) -> None: ...


class SurveyTelemetry:
    """Publish scalar-only survey diagnostics through an injected callback."""

    def __init__(self, publish: Callable[[TaskEventType, dict[str, object], float | None], None]) -> None:
        self._publish = publish
        self._counts: dict[str, int] = {
            "input_paper_count": 0,
            "input_statement_count": 0,
            "citation_capable_statement_count": 0,
            "core_paper_count": 0,
            "registered_citation_count": 0,
            "taxonomy_family_count": 0,
            "comparison_row_count": 0,
        }
        self._call_input_chars: dict[tuple[str, int], int] = {}

    def update_input_counts(self, **counts: int) -> None:
        self._counts.update({key: max(0, int(value)) for key, value in counts.items()})

    def stage_started(self) -> None:
        self._emit(TaskEventType.SURVEY_STAGE_STARTED, {"substage": "survey"})

    def stage_completed(self) -> None:
        self._emit(TaskEventType.SURVEY_STAGE_COMPLETED, {"substage": "survey"})

    def stage_aborted(self, error: Exception) -> None:
        self._emit(
            TaskEventType.SURVEY_STAGE_ABORTED,
            {"substage": "survey", **_failure_payload(error)},
        )

    def substage_started(self, substage: str) -> float:
        started = time.monotonic()
        self._emit(TaskEventType.SURVEY_SUBSTAGE_STARTED, {"substage": substage})
        return started

    def substage_completed(self, substage: str, started: float) -> None:
        self._emit(
            TaskEventType.SURVEY_SUBSTAGE_COMPLETED,
            {"substage": substage},
            _elapsed_ms(started),
        )

    def substage_failed(self, substage: str, started: float, error: Exception) -> None:
        self._emit(
            TaskEventType.SURVEY_SUBSTAGE_FAILED,
            {"substage": substage, **_failure_payload(error)},
            _elapsed_ms(started),
        )

    def llm_started(self, substage: str, call_index: int, estimated_input_chars: int) -> float:
        started = time.monotonic()
        self._call_input_chars[(substage, call_index)] = max(0, estimated_input_chars)
        self._emit(
            TaskEventType.SURVEY_LLM_CALL_STARTED,
            {
                "substage": substage,
                "call_index": call_index,
                "structured_output": True,
                "estimated_input_char_count": max(0, estimated_input_chars),
            },
        )
        return started

    def llm_succeeded(self, substage: str, call_index: int, started: float) -> None:
        self._emit(
            TaskEventType.SURVEY_LLM_CALL_SUCCEEDED,
            {
                "substage": substage,
                "call_index": call_index,
                "structured_output": True,
                "provider_response_reached": True,
                "json_parse_reached": True,
                "schema_validation_reached": True,
                "application_mapping_reached": True,
                "estimated_input_char_count": self._call_input_chars.pop((substage, call_index), 0),
            },
            _elapsed_ms(started),
        )

    def llm_failed(self, substage: str, call_index: int, started: float, error: Exception) -> None:
        self._emit(
            TaskEventType.SURVEY_LLM_CALL_FAILED,
            {
                "substage": substage,
                "call_index": call_index,
                "structured_output": True,
                "estimated_input_char_count": self._call_input_chars.pop((substage, call_index), 0),
                **_failure_payload(error),
            },
            _elapsed_ms(started),
        )

    def _emit(self, event_type: TaskEventType, payload: dict[str, object], duration_ms: float | None = None) -> None:
        safe = {**self._counts, **payload, "attempt_count": None, "retry_count": None}
        try:
            self._publish(event_type, safe, duration_ms)
        except Exception:
            # Observability is deliberately never a business-control dependency.
            return


class NullSurveyTelemetry:
    """No-op observer used when production diagnostics are not bound."""

    def stage_started(self) -> None: pass
    def stage_completed(self) -> None: pass
    def stage_aborted(self, error: Exception) -> None: pass
    def substage_started(self, substage: str) -> float: return 0.0
    def substage_completed(self, substage: str, started: float) -> None: pass
    def substage_failed(self, substage: str, started: float, error: Exception) -> None: pass
    def llm_started(self, substage: str, call_index: int, estimated_input_chars: int) -> float: return 0.0
    def llm_succeeded(self, substage: str, call_index: int, started: float) -> None: pass
    def llm_failed(self, substage: str, call_index: int, started: float, error: Exception) -> None: pass
    def update_input_counts(self, **counts: int) -> None: pass


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.monotonic() - started) * 1000) if started else 0.0


def _failure_payload(error: Exception) -> dict[str, object]:
    """Classify locally; no exception text or provider payload is persisted."""

    chain = list(_exception_chain(error))
    category = _failure_category(chain)
    types = {type(item) for item in chain}
    provider_response = any(
        isinstance(item, (AnalysisLLMResponseError, AnalysisSchemaValidationError, ValidationError))
        for item in chain
    )
    json_reached = any(isinstance(item, (AnalysisSchemaValidationError, ValidationError)) for item in chain)
    schema_reached = any(isinstance(item, (ReportSchemaValidationError, ValidationError)) for item in chain)
    payload: dict[str, object] = {
        "failure_category": category,
        "safe_exception_class": _safe_exception_class(category, types),
        "provider_response_reached": provider_response,
        "json_parse_reached": json_reached,
        "schema_validation_reached": schema_reached,
        "application_mapping_reached": category not in {"STRUCTURED_OUTPUT_PARSE", "SCHEMA_VALIDATION"},
    }
    validation_error = next(
        (item for item in chain if isinstance(item, ReportSchemaValidationError)),
        None,
    )
    if validation_error is not None:
        payload.update(
            {
                "validation_rule": getattr(validation_error, "validation_rule", str(validation_error)),
                "validation_field": getattr(validation_error, "validation_field", "citation_safe_validation"),
                "violation_count": 1,
            }
        )
    return payload


def _exception_chain(error: BaseException):
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _failure_category(chain: list[BaseException]) -> str:
    for item in chain:
        status = getattr(item, "status_code", None)
        if status == 402: return "PROVIDER_BILLING"
        if status in (401, 403): return "PROVIDER_AUTH"
        if status == 429: return "PROVIDER_RATE_LIMIT"
        if isinstance(status, int) and 500 <= status <= 599: return "PROVIDER_SERVER_ERROR"
    if any(isinstance(item, AnalysisLLMResponseError) for item in chain): return "STRUCTURED_OUTPUT_PARSE"
    if any(isinstance(item, (AnalysisSchemaValidationError, ValidationError)) for item in chain): return "SCHEMA_VALIDATION"
    if any(isinstance(item, ReportSchemaValidationError) for item in chain): return "SURVEY_REPORT_VALIDATION_ERROR"
    names = " ".join(type(item).__name__.casefold() for item in chain)
    messages = " ".join(str(item).casefold() for item in chain)
    if "context" in names + messages and ("length" in names + messages or "maximum" in names + messages): return "CONTEXT_LENGTH"
    if "timeout" in names + messages: return "PROVIDER_TIMEOUT"
    if "connection" in names or "connect" in names or "network" in names: return "PROVIDER_CONNECTION"
    if "empty" in names + messages and "response" in names + messages: return "EMPTY_RESPONSE"
    return "UNKNOWN"


def _safe_exception_class(category: str, types: set[type]) -> str:
    if category == "PROVIDER_TIMEOUT": return "ProviderTimeoutError"
    if category == "PROVIDER_CONNECTION": return "ProviderConnectionError"
    if category == "PROVIDER_AUTH": return "ProviderAuthError"
    if category == "PROVIDER_BILLING": return "ProviderBillingError"
    if category == "PROVIDER_RATE_LIMIT": return "ProviderRateLimitError"
    if category == "PROVIDER_SERVER_ERROR": return "ProviderServerError"
    if category == "STRUCTURED_OUTPUT_PARSE": return "AnalysisLLMResponseError"
    if category == "SCHEMA_VALIDATION": return "AnalysisSchemaValidationError"
    if category == "SURVEY_REPORT_VALIDATION_ERROR": return "ReportSchemaValidationError"
    return next(iter(types)).__name__ if types else "UnknownError"
