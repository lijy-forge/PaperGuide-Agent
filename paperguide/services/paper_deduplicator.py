"""Deterministic candidate-paper grouping and metadata merging."""

from collections.abc import Callable, Iterable
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from paperguide.domain import Author, FullTextStatus, PaperCandidate, PaperSource

from .metadata_normalizer import MetadataNormalizer
from .paper_matcher import PaperMatcher, PaperMatchResult


class MergedPaperGroup(BaseModel):
    """Describe the source candidates merged into one canonical paper."""

    model_config = ConfigDict(extra="forbid")

    canonical_paper_id: UUID
    merged_paper_ids: list[UUID]
    matched_by: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class DeduplicationResult(BaseModel):
    """Contain deduplicated papers and an explainable merge audit trail."""

    model_config = ConfigDict(extra="forbid")

    papers: list[PaperCandidate]
    original_count: int = Field(ge=0)
    deduplicated_count: int = Field(ge=0)
    merged_groups: list[MergedPaperGroup]
    warnings: list[str]


class PaperDeduplicator:
    """Group matching candidates and merge them without mutating inputs."""

    CANONICAL_DOI_WEIGHT = 1000
    CANONICAL_ARXIV_WEIGHT = 500
    CANONICAL_IDENTIFIER_WEIGHT = 120
    CANONICAL_ABSTRACT_WEIGHT = 80
    CANONICAL_VENUE_WEIGHT = 50
    CANONICAL_PDF_WEIGHT = 40
    CANONICAL_AUTHOR_WEIGHT = 10
    CANONICAL_AFFILIATION_WEIGHT = 2
    CANONICAL_METADATA_FIELD_WEIGHT = 3

    FULL_TEXT_STATUS_ORDER = (
        FullTextStatus.FAILED,
        FullTextStatus.UNAVAILABLE,
        FullTextStatus.UNKNOWN,
        FullTextStatus.AVAILABLE,
    )
    MATCH_METHOD_ORDER = (
        "doi",
        "arxiv_id",
        "semantic_scholar_id",
        "openalex_id",
        "normalized_title",
        "fuzzy_title",
        "authors",
        "publication_year",
    )

    def __init__(self, matcher: PaperMatcher | None = None):
        self.matcher = matcher or PaperMatcher()

    def deduplicate(self, papers: list[PaperCandidate]) -> DeduplicationResult:
        """Return merged copies of duplicate candidates and merge diagnostics."""

        if not papers:
            return DeduplicationResult(
                papers=[],
                original_count=0,
                deduplicated_count=0,
                merged_groups=[],
                warnings=[],
            )

        parents = list(range(len(papers)))
        matching_edges: list[tuple[int, int, PaperMatchResult]] = []

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left_index: int, right_index: int) -> None:
            left_root = find(left_index)
            right_root = find(right_index)
            if left_root != right_root:
                parents[right_root] = left_root

        for left_index, left in enumerate(papers):
            for right_index in range(left_index + 1, len(papers)):
                result = self.matcher.match(left, papers[right_index])
                if result.is_match:
                    union(left_index, right_index)
                    matching_edges.append((left_index, right_index, result))

        grouped_indices: dict[int, list[int]] = {}
        for index in range(len(papers)):
            grouped_indices.setdefault(find(index), []).append(index)

        merged_papers: list[PaperCandidate] = []
        merged_groups: list[MergedPaperGroup] = []
        warnings: list[str] = []
        for indices in grouped_indices.values():
            records = [papers[index] for index in indices]
            canonical_position = self._select_canonical_position(records)
            canonical = records[canonical_position]
            if len(records) == 1:
                merged_papers.append(canonical.model_copy(deep=True))
                continue

            merged, group_warnings = self._merge_group(records, canonical_position)
            merged_papers.append(merged)
            warnings.extend(group_warnings)

            index_set = set(indices)
            group_edges = [
                result
                for left_index, right_index, result in matching_edges
                if left_index in index_set and right_index in index_set
            ]
            matched_methods = {
                method for result in group_edges for method in result.matched_by
            }
            merged_groups.append(
                MergedPaperGroup(
                    canonical_paper_id=canonical.id,
                    merged_paper_ids=sorted(
                        (paper.id for paper in records if paper.id != canonical.id),
                        key=str,
                    ),
                    matched_by=[
                        method
                        for method in self.MATCH_METHOD_ORDER
                        if method in matched_methods
                    ],
                    confidence=min(result.confidence for result in group_edges),
                )
            )

        return DeduplicationResult(
            papers=merged_papers,
            original_count=len(papers),
            deduplicated_count=len(merged_papers),
            merged_groups=merged_groups,
            warnings=list(dict.fromkeys(warnings)),
        )

    def _select_canonical_position(self, papers: list[PaperCandidate]) -> int:
        return max(
            range(len(papers)),
            key=lambda index: (self._canonical_score(papers[index]), -index),
        )

    def _canonical_score(self, paper: PaperCandidate) -> int:
        identifiers = (
            paper.doi,
            paper.arxiv_id,
            paper.semantic_scholar_id,
            paper.openalex_id,
        )
        optional_metadata = (
            paper.abstract,
            paper.publication_year,
            paper.venue,
            paper.landing_page_url,
            paper.pdf_url,
            paper.citation_count,
            paper.selection_reason,
        )
        return (
            self.CANONICAL_DOI_WEIGHT * bool(MetadataNormalizer.normalize_doi(paper.doi))
            + self.CANONICAL_ARXIV_WEIGHT
            * bool(MetadataNormalizer.normalize_arxiv_id(paper.arxiv_id))
            + self.CANONICAL_IDENTIFIER_WEIGHT
            * sum(bool(value and str(value).strip()) for value in identifiers)
            + self.CANONICAL_ABSTRACT_WEIGHT * bool(paper.abstract and paper.abstract.strip())
            + self.CANONICAL_VENUE_WEIGHT * bool(paper.venue and paper.venue.strip())
            + self.CANONICAL_PDF_WEIGHT
            * bool(MetadataNormalizer.normalize_url(paper.pdf_url))
            + self.CANONICAL_AUTHOR_WEIGHT * len(paper.authors)
            + self.CANONICAL_AFFILIATION_WEIGHT
            * sum(len(author.affiliations) for author in paper.authors)
            + self.CANONICAL_METADATA_FIELD_WEIGHT
            * sum(value is not None and value != "" for value in optional_metadata)
        )

    def _merge_group(
        self, papers: list[PaperCandidate], canonical_position: int
    ) -> tuple[PaperCandidate, list[str]]:
        canonical = papers[canonical_position]
        warnings: list[str] = []
        ranked = self._ranked_papers(papers)

        doi = self._merge_identifier(
            "DOI", papers, canonical, MetadataNormalizer.normalize_doi, warnings
        )
        arxiv_id = self._merge_identifier(
            "arXiv ID",
            papers,
            canonical,
            MetadataNormalizer.normalize_arxiv_id,
            warnings,
        )
        semantic_scholar_id = self._merge_identifier(
            "Semantic Scholar ID",
            papers,
            canonical,
            self._normalize_external_id,
            warnings,
        )
        openalex_id = self._merge_identifier(
            "OpenAlex ID",
            papers,
            canonical,
            self._normalize_external_id,
            warnings,
        )

        title = max((paper.title for paper in papers), key=self._title_score)
        abstract = self._longest_nonempty(paper.abstract for paper in papers)
        publication_year = self._merge_year(papers, canonical, ranked, warnings)
        venue = self._merge_venue(papers, canonical, ranked, warnings)

        values = canonical.model_dump()
        values.update(
            {
                "title": title,
                "normalized_title": MetadataNormalizer.normalize_title(title),
                "abstract": abstract,
                "authors": self._merge_authors(papers, canonical),
                "publication_year": publication_year,
                "venue": venue,
                "doi": doi,
                "arxiv_id": arxiv_id,
                "semantic_scholar_id": semantic_scholar_id,
                "openalex_id": openalex_id,
                "sources": self._merge_sources(papers),
                "landing_page_url": self._merge_landing_url(papers, canonical),
                "pdf_url": self._merge_pdf_url(papers, canonical),
                "citation_count": self._maximum_optional(
                    paper.citation_count for paper in papers
                ),
                "full_text_status": max(
                    (paper.full_text_status for paper in papers),
                    key=self.FULL_TEXT_STATUS_ORDER.index,
                ),
                "relevance_score": self._maximum_optional(
                    paper.relevance_score for paper in papers
                ),
                "selection_reason": self._merge_selection_reasons(
                    papers, canonical
                ),
            }
        )
        return PaperCandidate.model_validate(values), warnings

    def _merge_identifier(
        self,
        label: str,
        papers: list[PaperCandidate],
        canonical: PaperCandidate,
        normalizer: Callable[[str | None], str | None],
        warnings: list[str],
    ) -> str | None:
        attribute = {
            "DOI": "doi",
            "arXiv ID": "arxiv_id",
            "Semantic Scholar ID": "semantic_scholar_id",
            "OpenAlex ID": "openalex_id",
        }[label]
        normalized_values = {
            normalized
            for paper in papers
            if (normalized := normalizer(getattr(paper, attribute))) is not None
        }
        canonical_value = normalizer(getattr(canonical, attribute))
        selected = canonical_value
        if selected is None:
            selected = next(
                (
                    normalizer(getattr(paper, attribute))
                    for paper in self._ranked_papers(papers)
                    if normalizer(getattr(paper, attribute)) is not None
                ),
                None,
            )
        if len(normalized_values) > 1:
            warnings.append(
                f"Conflicting {label} values for canonical paper {canonical.id}; "
                f"kept {selected!r} and did not overwrite it silently."
            )
        return selected

    def _merge_year(
        self,
        papers: list[PaperCandidate],
        canonical: PaperCandidate,
        ranked: list[PaperCandidate],
        warnings: list[str],
    ) -> int | None:
        years = {paper.publication_year for paper in papers if paper.publication_year}
        if not years:
            return None
        if len(years) == 1:
            return next(iter(years))
        if max(years) - min(years) <= 1:
            candidates = [paper for paper in ranked if paper.publication_year is not None]
            return max(
                candidates,
                key=lambda paper: (
                    bool(MetadataNormalizer.normalize_doi(paper.doi)),
                    bool(paper.venue and paper.venue.strip()),
                    self._canonical_score(paper),
                ),
            ).publication_year
        selected = canonical.publication_year
        if selected is None:
            selected = next(
                paper.publication_year
                for paper in ranked
                if paper.publication_year is not None
            )
        warnings.append(
            f"Conflicting publication years for canonical paper {canonical.id}; "
            f"kept {selected}."
        )
        return selected

    def _merge_venue(
        self,
        papers: list[PaperCandidate],
        canonical: PaperCandidate,
        ranked: list[PaperCandidate],
        warnings: list[str],
    ) -> str | None:
        venues = {
            paper.venue.strip()
            for paper in papers
            if paper.venue and paper.venue.strip()
        }
        selected = canonical.venue.strip() if canonical.venue else None
        if selected is None:
            selected = next(
                (
                    paper.venue.strip()
                    for paper in ranked
                    if paper.venue and paper.venue.strip()
                ),
                None,
            )
        if len({venue.casefold() for venue in venues}) > 1:
            warnings.append(
                f"Conflicting venue values for canonical paper {canonical.id}; "
                f"kept {selected!r}."
            )
        return selected

    def _merge_authors(
        self, papers: list[PaperCandidate], canonical: PaperCandidate
    ) -> list[Author]:
        grouped: dict[str, list[Author]] = {}
        for paper in papers:
            for author in paper.authors:
                key = MetadataNormalizer.normalize_author_name(
                    author.normalized_name or author.full_name
                )
                if key:
                    grouped.setdefault(key, []).append(author)

        canonical_order = [
            MetadataNormalizer.normalize_author_name(
                author.normalized_name or author.full_name
            )
            for author in canonical.authors
        ]
        ordered_keys = list(dict.fromkeys(key for key in canonical_order if key))
        ordered_keys.extend(sorted(set(grouped) - set(ordered_keys)))

        merged: list[Author] = []
        for key in ordered_keys:
            candidates = grouped[key]
            preferred = max(
                candidates,
                key=lambda author: (
                    len(author.affiliations),
                    bool(author.normalized_name),
                    self._natural_case_score(author.full_name),
                    len(author.full_name),
                    author.full_name.casefold(),
                ),
            )
            affiliations = sorted(
                {
                    affiliation.strip()
                    for author in candidates
                    for affiliation in author.affiliations
                    if affiliation.strip()
                },
                key=str.casefold,
            )
            merged.append(
                Author(
                    full_name=preferred.full_name,
                    normalized_name=key,
                    affiliations=affiliations,
                )
            )
        return merged

    @staticmethod
    def _merge_sources(papers: list[PaperCandidate]) -> list[PaperSource]:
        present = {source for paper in papers for source in paper.sources}
        return [source for source in PaperSource if source in present]

    def _merge_landing_url(
        self, papers: list[PaperCandidate], canonical: PaperCandidate
    ) -> str | None:
        canonical_url = MetadataNormalizer.normalize_url(canonical.landing_page_url)
        if canonical_url:
            return canonical_url
        urls = sorted(
            {
                normalized
                for paper in papers
                if (
                    normalized := MetadataNormalizer.normalize_url(
                        paper.landing_page_url
                    )
                )
                is not None
            }
        )
        return urls[0] if urls else None

    def _merge_pdf_url(
        self, papers: list[PaperCandidate], canonical: PaperCandidate
    ) -> str | None:
        candidates = {
            normalized
            for paper in papers
            if (normalized := MetadataNormalizer.normalize_url(paper.pdf_url))
            is not None
        }
        if not candidates:
            return None
        canonical_url = MetadataNormalizer.normalize_url(canonical.pdf_url)
        return max(
            candidates,
            key=lambda url: (
                (urlsplit(url).hostname or "").casefold() == "arxiv.org",
                urlsplit(url).path.casefold().endswith(".pdf"),
                url == canonical_url,
                url,
            ),
        )

    @staticmethod
    def _merge_selection_reasons(
        papers: list[PaperCandidate], canonical: PaperCandidate
    ) -> str | None:
        canonical_reason = (
            canonical.selection_reason.strip() if canonical.selection_reason else None
        )
        reasons = {
            paper.selection_reason.strip()
            for paper in papers
            if paper.selection_reason and paper.selection_reason.strip()
        }
        ordered: list[str] = []
        if canonical_reason:
            ordered.append(canonical_reason)
        ordered.extend(sorted(reasons - set(ordered), key=str.casefold))
        return " | ".join(ordered) if ordered else None

    def _ranked_papers(self, papers: list[PaperCandidate]) -> list[PaperCandidate]:
        return [
            paper
            for _, paper in sorted(
                enumerate(papers),
                key=lambda item: (-self._canonical_score(item[1]), item[0]),
            )
        ]

    @classmethod
    def _title_score(cls, title: str) -> tuple[int, int, int, str]:
        return (
            cls._natural_case_score(title),
            len(title.split()),
            len(title),
            title,
        )

    @staticmethod
    def _natural_case_score(value: str) -> int:
        letters = "".join(character for character in value if character.isalpha())
        if not letters:
            return 0
        return int(not letters.islower() and not letters.isupper())

    @staticmethod
    def _longest_nonempty(values: Iterable[str | None]) -> str | None:
        candidates = [value.strip() for value in values if value and value.strip()]
        return max(candidates, key=lambda value: (len(value), value)) if candidates else None

    @staticmethod
    def _maximum_optional(
        values: Iterable[int | float | None],
    ) -> int | float | None:
        candidates = [value for value in values if value is not None]
        return max(candidates) if candidates else None

    @staticmethod
    def _normalize_external_id(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/").casefold()
        return normalized or None
