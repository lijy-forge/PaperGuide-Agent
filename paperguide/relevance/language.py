"""Deterministic language classification for research-question presentation."""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def language_from_question(question: str) -> str:
    """Return the supported public-report locale for one research question."""

    return "zh" if _CJK_RE.search(question) else "en"


def normalize_query_language(value: str | None, *, question: str) -> str:
    """Normalize an intent locale, falling back deterministically to its question."""

    normalized = (value or "").strip().casefold().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    return language_from_question(question)
