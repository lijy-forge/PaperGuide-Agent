"""Public search-pipeline interface for PaperGuide AI."""

from .result import SearchResult
from .search_pipeline import PaperSearchPipeline

__all__ = ["PaperSearchPipeline", "SearchResult"]
