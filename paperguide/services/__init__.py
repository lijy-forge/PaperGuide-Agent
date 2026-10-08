"""Deterministic metadata services for PaperGuide AI."""

from .full_text import INGESTIBLE_FULL_TEXT_STATUSES, can_ingest_full_text
from .metadata_normalizer import MetadataNormalizer
from .paper_deduplicator import (
    DeduplicationResult,
    MergedPaperGroup,
    PaperDeduplicator,
)
from .paper_matcher import PaperMatcher, PaperMatchResult

__all__ = [
    "INGESTIBLE_FULL_TEXT_STATUSES",
    "DeduplicationResult",
    "MergedPaperGroup",
    "MetadataNormalizer",
    "can_ingest_full_text",
    "PaperDeduplicator",
    "PaperMatcher",
    "PaperMatchResult",
]
