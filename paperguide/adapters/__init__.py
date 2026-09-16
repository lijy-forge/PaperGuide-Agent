"""External data-source adapters for PaperGuide AI."""

from .base import RetrieverProtocol
from .arxiv import (
    ArxivClient,
    ArxivClientError,
    ArxivConfig,
    ArxivInvalidResponseError,
    ArxivMapper,
    ArxivNetworkError,
)
from .semantic_scholar import (
    SemanticScholarClient,
    SemanticScholarConfig,
    SemanticScholarError,
    SemanticScholarInvalidResponseError,
    SemanticScholarMapper,
    SemanticScholarNetworkError,
)

__all__ = [
    "ArxivClient",
    "ArxivClientError",
    "ArxivConfig",
    "ArxivInvalidResponseError",
    "ArxivMapper",
    "ArxivNetworkError",
    "RetrieverProtocol",
    "SemanticScholarClient",
    "SemanticScholarConfig",
    "SemanticScholarError",
    "SemanticScholarInvalidResponseError",
    "SemanticScholarMapper",
    "SemanticScholarNetworkError",
]
