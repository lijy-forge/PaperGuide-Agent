"""Versioned prompts used by PaperGuide analysis components."""

from .evidence_verifier import (
    EVIDENCE_VERIFIER_PROMPT_VERSION,
    EVIDENCE_VERIFIER_SYSTEM_PROMPT,
    build_evidence_verifier_prompt,
)
from .paper_reader import (
    PAPER_READER_PROMPT_VERSION,
    PAPER_READER_SYSTEM_PROMPT,
    build_paper_reader_user_prompt,
)

__all__ = [
    "EVIDENCE_VERIFIER_PROMPT_VERSION",
    "EVIDENCE_VERIFIER_SYSTEM_PROMPT",
    "PAPER_READER_PROMPT_VERSION",
    "PAPER_READER_SYSTEM_PROMPT",
    "build_paper_reader_user_prompt",
    "build_evidence_verifier_prompt",
]
