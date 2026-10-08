"""Public search-pipeline interface for PaperGuide AI."""

from .ranking import rank_by_question
from .result import SearchResult
from .search_pipeline import PaperSearchPipeline

__all__ = ["PaperSearchPipeline", "SearchResult", "rank_by_question"]
