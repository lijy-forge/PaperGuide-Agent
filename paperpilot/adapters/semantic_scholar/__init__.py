"""Public Semantic Scholar adapter interface."""

from .client import (
    SemanticScholarClient,
    SemanticScholarConfig,
    SemanticScholarError,
    SemanticScholarInvalidResponseError,
    SemanticScholarNetworkError,
)
from .mapper import SemanticScholarMapper

__all__ = [
    "SemanticScholarClient",
    "SemanticScholarConfig",
    "SemanticScholarError",
    "SemanticScholarInvalidResponseError",
    "SemanticScholarMapper",
    "SemanticScholarNetworkError",
]
