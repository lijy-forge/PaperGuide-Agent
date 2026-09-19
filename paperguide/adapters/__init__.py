"""External data-source adapters for PaperGuide AI."""

from .arxiv import (
    ArxivClient,
    ArxivClientError,
    ArxivConfig,
    ArxivInvalidResponseError,
    ArxivMapper,
    ArxivNetworkError,
)
from .base import RetrieverProtocol
from .crossref import (
    CrossrefClient,
    CrossrefConfig,
    CrossrefError,
    CrossrefInvalidResponseError,
    CrossrefMapper,
    CrossrefNetworkError,
)
from .openalex import (
    OpenAlexClient,
    OpenAlexConfig,
    OpenAlexError,
    OpenAlexInvalidResponseError,
    OpenAlexMapper,
    OpenAlexNetworkError,
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
    "CrossrefClient",
    "CrossrefConfig",
    "CrossrefError",
    "CrossrefInvalidResponseError",
    "CrossrefMapper",
    "CrossrefNetworkError",
    "OpenAlexClient",
    "OpenAlexConfig",
    "OpenAlexError",
    "OpenAlexInvalidResponseError",
    "OpenAlexMapper",
    "OpenAlexNetworkError",
    "RetrieverProtocol",
    "SemanticScholarClient",
    "SemanticScholarConfig",
    "SemanticScholarError",
    "SemanticScholarInvalidResponseError",
    "SemanticScholarMapper",
    "SemanticScholarNetworkError",
]
