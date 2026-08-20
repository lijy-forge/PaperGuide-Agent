"""Deterministic guard for public progress payloads."""

import re
from typing import Any

from .models import ProgressEventPayload


class PublicProgressValidator:
    """Reject payload names and values that could expose internal content."""

    _FORBIDDEN = re.compile(
        r"(?:prompt|system_prompt|raw_response|authorization|api[_-]?key|"
        r"bearer|token|paper_id|statement_key|evidence_id|evidence_key|"
        r"lease|fencing|execution_id|full_text|pdf_text|quote|"
        r"[a-z]:[\\/]|/(?:app|home|tmp|var|users?)/)",
        re.IGNORECASE,
    )

    def validate(self, payload: ProgressEventPayload) -> ProgressEventPayload:
        """Return a deep-safe normalized payload or reject unsafe text."""

        dumped = payload.model_dump(exclude_none=True)
        self._scan(dumped)
        return ProgressEventPayload.model_validate(dumped)

    def _scan(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if self._FORBIDDEN.search(str(key)):
                    raise ValueError("progress payload contains a forbidden field")
                self._scan(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._scan(item)
        elif isinstance(value, str) and self._FORBIDDEN.search(value):
            raise ValueError("progress payload contains unsafe content")
