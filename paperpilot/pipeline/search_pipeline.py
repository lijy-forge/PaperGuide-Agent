"""Synchronous multi-retriever search orchestration for PaperPilot AI."""

import re

from paperpilot.adapters import RetrieverProtocol
from paperpilot.domain import PaperCandidate, PaperSource, ResearchConfig
from paperpilot.services import PaperDeduplicator

from .result import SearchResult


class PaperSearchPipeline:
    """Run selected retrievers, isolate failures, and deduplicate candidates."""

    _IMPLEMENTATION_SUFFIX_RE = re.compile(r"(?:Client|Retriever)$")
    _CAMEL_CASE_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")
    _YEAR_FILTER_OVERFETCH_FACTOR = 5
    _MAX_RETRIEVER_RESULTS = 50

    def __init__(
        self,
        retrievers: list[RetrieverProtocol],
        deduplicator: PaperDeduplicator | None = None,
    ):
        self._retrievers = [
            (self._resolve_source_name(retriever), retriever)
            for retriever in retrievers
        ]
        self._deduplicator = deduplicator or PaperDeduplicator()

    def search(self, config: ResearchConfig) -> SearchResult:
        """Search configured sources and return a bounded, deduplicated result."""

        configured_sources = {source.value for source in config.sources}
        candidates: list[PaperCandidate] = []
        source_results: dict[str, int] = {}
        source_errors: dict[str, str] = {}
        warnings: list[str] = []
        result_limit = config.max_papers
        if config.start_year is not None or config.end_year is not None:
            result_limit = min(
                config.max_papers * self._YEAR_FILTER_OVERFETCH_FACTOR,
                self._MAX_RETRIEVER_RESULTS,
            )

        for source_name, retriever in self._retrievers:
            if source_name not in configured_sources:
                continue
            try:
                source_papers = retriever.search(
                    config.question,
                    max_results=result_limit,
                )
                if not isinstance(source_papers, list):
                    raise TypeError("retriever search result must be a list")
                source_results[source_name] = source_results.get(source_name, 0) + len(
                    source_papers
                )
                candidates.extend(
                    paper
                    for paper in source_papers
                    if self._matches_year_scope(paper, config)
                )
            except Exception as error:
                message = str(error).strip() or type(error).__name__
                existing_error = source_errors.get(source_name)
                source_errors[source_name] = (
                    f"{existing_error} | {message}" if existing_error else message
                )
                warnings.append(f"Retriever {source_name} failed: {message}")

        deduplication = self._deduplicator.deduplicate(candidates)
        warnings.extend(deduplication.warnings)
        papers = self._sort_by_relevance(deduplication.papers)

        return SearchResult(
            papers=papers[: config.max_papers],
            source_results=source_results,
            source_errors=source_errors,
            warnings=list(dict.fromkeys(warnings)),
            total_found=len(candidates),
            total_after_dedup=deduplication.deduplicated_count,
        )

    @staticmethod
    def _sort_by_relevance(papers: list[PaperCandidate]) -> list[PaperCandidate]:
        if not any(paper.relevance_score is not None for paper in papers):
            return list(papers)
        return sorted(
            papers,
            key=lambda paper: (
                paper.relevance_score is None,
                -(paper.relevance_score or 0.0),
            ),
        )

    @staticmethod
    def _matches_year_scope(
        paper: PaperCandidate,
        config: ResearchConfig,
    ) -> bool:
        year = paper.publication_year
        if config.start_year is not None and (year is None or year < config.start_year):
            return False
        if config.end_year is not None and (year is None or year > config.end_year):
            return False
        return True

    @classmethod
    def _resolve_source_name(cls, retriever: RetrieverProtocol) -> str:
        if not isinstance(retriever, RetrieverProtocol):
            raise TypeError("retriever must satisfy RetrieverProtocol")

        declared_source = getattr(retriever, "source", None)
        if isinstance(declared_source, PaperSource):
            return declared_source.value
        if isinstance(declared_source, str) and declared_source.strip():
            source_name = declared_source.strip().casefold()
        else:
            implementation_name = cls._IMPLEMENTATION_SUFFIX_RE.sub(
                "", type(retriever).__name__
            )
            source_name = cls._CAMEL_CASE_BOUNDARY_RE.sub(
                "_", implementation_name
            ).casefold()

        valid_sources = {source.value for source in PaperSource}
        if source_name not in valid_sources:
            raise ValueError(
                f"Unable to resolve PaperSource for {type(retriever).__name__}; "
                "declare a valid 'source' attribute"
            )
        return source_name
