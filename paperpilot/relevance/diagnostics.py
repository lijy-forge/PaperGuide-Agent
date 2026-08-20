"""Content-free diagnostics for production retrieval planning."""

from __future__ import annotations

import re
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from paperpilot.analysis import (
    AnalysisLLMInvocationError,
    AnalysisLLMResponseError,
    AnalysisSchemaValidationError,
)


_SAFE_CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,80}$")


class PlanningStageDiagnostic(BaseModel):
    """Safe scalar facts about one planner or expansion operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str
    outcome: str
    failure_category: str = "NONE"
    exception_class_safe: str = "None"
    attempt_count: int = Field(default=1, ge=1)
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    fallback_query_count: int = Field(default=0, ge=0)
    fallback_reason_code: str = "NONE"
    json_parse_reached: bool = False
    schema_validation_reached: bool = False
    output_count: int = Field(default=0, ge=0)
    required_concept_count: int = Field(default=0, ge=0)
    related_concept_count: int = Field(default=0, ge=0)
    relation_requirement_count: int = Field(default=0, ge=0)
    exclusion_concept_count: int = Field(default=0, ge=0)
    domain_present: bool = False
    time_range_present: bool = False
    query_language_present: bool = False
    zh_term_count: int = Field(default=0, ge=0)
    en_term_count: int = Field(default=0, ge=0)
    mixed_term_count: int = Field(default=0, ge=0)


PlanningDiagnosticCallback = Callable[[PlanningStageDiagnostic], None]


def classify_planning_failure(error: BaseException, *, stage: str) -> tuple[str, str, bool, bool]:
    """Classify an exception chain without returning messages or response data."""

    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(chain) < 8:
        chain.append(current)
        current = current.__cause__ or current.__context__
    names = " ".join(type(item).__name__.casefold() for item in chain)
    messages = " ".join(str(item).casefold() for item in chain)
    json_parse_reached = isinstance(error, (AnalysisLLMResponseError, AnalysisSchemaValidationError))
    schema_validation_reached = isinstance(error, AnalysisSchemaValidationError)

    if isinstance(error, AnalysisLLMResponseError):
        category = "EMPTY_RESPONSE" if "non-empty" in messages else "STRUCTURED_OUTPUT_PARSE"
    elif isinstance(error, AnalysisSchemaValidationError) or "validationerror" in names:
        category = "SCHEMA_VALIDATION"
    elif "timeout" in names or "timed out" in messages:
        category = "PROVIDER_TIMEOUT"
    elif "ratelimit" in names or "toomanyrequests" in names or "429" in messages:
        category = "PROVIDER_RATE_LIMIT"
    elif any(token in names for token in ("authenticationerror", "permissiondenied", "unauthorized")) or "401" in messages:
        category = "PROVIDER_AUTH"
    elif any(token in names for token in ("connectionerror", "urlerror", "networkerror", "connecterror")):
        category = "PROVIDER_CONNECTION"
    elif any(token in names for token in ("servererror", "internalserver", "serviceunavailable")) or any(code in messages for code in ("500", "502", "503")):
        category = "PROVIDER_SERVER_ERROR"
    elif isinstance(error, AnalysisLLMInvocationError):
        category = "PROVIDER_CONNECTION"
    elif isinstance(error, (TypeError, ValueError)):
        category = "INVALID_PLANNER_OUTPUT" if stage == "intent_planner" else "INVALID_EXPANSION_OUTPUT"
    else:
        category = "APPLICATION_ERROR" if "error" in names else "UNKNOWN"

    class_name = type(chain[-1]).__name__ if chain else type(error).__name__
    if not _SAFE_CLASS.fullmatch(class_name):
        class_name = "UnknownException"
    return category, class_name, json_parse_reached, schema_validation_reached
