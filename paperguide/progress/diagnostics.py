"""Private, content-free diagnostics for PaperReader reliability analysis."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SAFE_CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,80}$")


FAILURE_CATEGORIES = frozenset(
    {
        "PROVIDER_AUTH",
        "PROVIDER_CONNECTION",
        "PROVIDER_TIMEOUT",
        "PROVIDER_RATE_LIMIT",
        "PROVIDER_SERVER_ERROR",
        "CONTEXT_LENGTH",
        "STRUCTURED_OUTPUT_PARSE",
        "SCHEMA_VALIDATION",
        "EMPTY_RESPONSE",
        "READER_INPUT_INVALID",
        "READER_APPLICATION_ERROR",
        "UNKNOWN",
    }
)


def summarize_reader_diagnostics(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Build an internal, content-free Reader summary from private events."""

    items: list[dict[str, Any]] = []
    failures: dict[str, int] = {}
    stage_outcome = "UNKNOWN"
    stage_elapsed_ms: float | None = None
    for event in events:
        event_type = str(event.get("event_type", ""))
        diagnostic = event.get("diagnostic")
        if not isinstance(diagnostic, Mapping):
            continue
        if event_type in {"reader_item_succeeded", "reader_item_failed"}:
            item = {
                key: diagnostic[key]
                for key in (
                    "item_index",
                    "total_items",
                    "safe_title_preview",
                    "elapsed_ms",
                    "outcome",
                    "failure_category",
                    "exception_class_safe",
                    "attempt_count",
                    "retry_count",
                )
                if key in diagnostic
            }
            items.append(item)
            category = diagnostic.get("failure_category")
            if isinstance(category, str):
                failures[category] = failures.get(category, 0) + 1
        elif event_type in {"reader_stage_completed", "reader_stage_aborted"}:
            stage_outcome = str(diagnostic.get("stage_outcome", "UNKNOWN"))
            raw_duration = event.get("duration_ms")
            stage_elapsed_ms = (
                float(raw_duration)
                if isinstance(raw_duration, (int, float))
                else None
            )
    return {
        "items": items,
        "failure_categories": failures,
        "stage_outcome": stage_outcome,
        "stage_elapsed_ms": stage_elapsed_ms,
    }


def sanitize_reader_exception(error: BaseException) -> dict[str, str]:
    """Map an exception chain to safe category/class fields only.

    No exception message, traceback, URL, prompt, response, or object repr is
    persisted. The classification is deterministic and intentionally narrow.
    """

    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(chain) < 8:
        chain.append(current)
        current = current.__cause__ or current.__context__
    names = " ".join(type(item).__name__.casefold() for item in chain)
    # Message text is inspected ephemerally for category matching only; it is
    # never returned or persisted.
    messages = " ".join(str(item).casefold() for item in chain)
    category = "UNKNOWN"
    if any(token in names for token in ("validationerror", "schemaschema")):
        category = "SCHEMA_VALIDATION"
    elif "jsondecodeerror" in names or "responseerror" in names:
        category = "STRUCTURED_OUTPUT_PARSE"
    elif "timeout" in names or "timeouterror" in names or "timed out" in messages:
        category = "PROVIDER_TIMEOUT"
    elif "ratelimit" in names or "toomanyrequests" in names or "rate limit" in messages or "429" in messages:
        category = "PROVIDER_RATE_LIMIT"
    elif any(token in names for token in ("connectionerror", "urlerror", "networkerror")):
        category = "PROVIDER_CONNECTION"
    elif any(token in names for token in ("authenticationerror", "permissionerror", "unauthorized")) or "unauthorized" in messages or "401" in messages:
        category = "PROVIDER_AUTH"
    elif any(token in names for token in ("badrequest", "contextlength", "invalidrequest")) or "context length" in messages or "maximum context" in messages:
        category = "CONTEXT_LENGTH"
    elif "emptyresponse" in names or "empty response" in messages:
        category = "EMPTY_RESPONSE"
    elif any(token in names for token in ("servererror", "internalserver", "serviceunavailable", "httpstatuserror")) or any(token in messages for token in ("500", "502", "503", "server error")):
        category = "PROVIDER_SERVER_ERROR"
    elif "papercontexterror" in names or "document" in names:
        category = "READER_INPUT_INVALID"
    elif "analysisllm" in names or "llm" in names:
        category = "READER_APPLICATION_ERROR"
    class_name = type(error).__name__
    if not _SAFE_CLASS.fullmatch(class_name):
        class_name = "UnknownException"
    return {"failure_category": category, "exception_class_safe": class_name}


def safe_diagnostic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a bounded scalar-only diagnostic payload.

    This is a final guard against accidental content-bearing values entering
    the private event channel.
    """

    allowed_types = (str, int, float, bool)
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not _SAFE_CLASS.fullmatch(key):
            continue
        if isinstance(value, allowed_types) or value is None:
            if isinstance(value, str):
                result[key] = value[:100]
            else:
                result[key] = value
    return result
