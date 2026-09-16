"""Deterministic metadata services for PaperGuide AI."""

from .metadata_normalizer import MetadataNormalizer
from .paper_deduplicator import (
    DeduplicationResult,
    MergedPaperGroup,
    PaperDeduplicator,
)
from .paper_matcher import PaperMatcher, PaperMatchResult

__all__ = [
    "DeduplicationResult",
    "MergedPaperGroup",
    "MetadataNormalizer",
    "PaperDeduplicator",
    "PaperMatcher",
    "PaperMatchResult",
]
