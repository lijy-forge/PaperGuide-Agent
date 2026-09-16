"""Map Semantic Scholar Graph API records to PaperGuide models."""

from collections.abc import Mapping
from typing import Any

from paperguide.domain import Author, FullTextStatus, PaperCandidate, PaperSource
from paperguide.services import MetadataNormalizer


class SemanticScholarMapper:
    """Convert a read-only Semantic Scholar record into a paper candidate."""

    @classmethod
    def map_paper(cls, record: Mapping[str, Any]) -> PaperCandidate:
        """Map one Graph API paper record without modifying the input."""

        paper_id = cls._optional_string(record.get("paperId"))
        if paper_id is None:
            raise ValueError("Semantic Scholar record is missing paperId")

        title = cls._clean_text(record.get("title"))
        if not title:
            raise ValueError("Semantic Scholar record is missing a title")

        raw_authors = record.get("authors")
        authors = []
        if raw_authors is not None:
            if not isinstance(raw_authors, list):
                raise ValueError("Semantic Scholar authors must be a list")
            for raw_author in raw_authors:
                if not isinstance(raw_author, Mapping):
                    continue
                name = cls._clean_text(raw_author.get("name"))
                if name:
                    authors.append(
                        Author(
                            full_name=name,
                            normalized_name=MetadataNormalizer.normalize_author_name(
                                name
                            ),
                            affiliations=[],
                        )
                    )

        external_ids = record.get("externalIds")
        if not isinstance(external_ids, Mapping):
            external_ids = {}
        open_access_pdf = record.get("openAccessPdf")
        pdf_url = None
        if isinstance(open_access_pdf, Mapping):
            pdf_url = MetadataNormalizer.normalize_url(
                cls._optional_string(open_access_pdf.get("url"))
            )

        return PaperCandidate(
            title=title,
            normalized_title=MetadataNormalizer.normalize_title(title),
            abstract=cls._clean_text(record.get("abstract")) or None,
            authors=authors,
            publication_year=record.get("year"),
            published_at=None,
            updated_at=None,
            venue=cls._clean_text(record.get("venue")) or None,
            doi=MetadataNormalizer.normalize_doi(
                cls._optional_string(external_ids.get("DOI"))
            ),
            arxiv_id=MetadataNormalizer.normalize_arxiv_id(
                cls._optional_string(external_ids.get("ArXiv"))
            ),
            semantic_scholar_id=paper_id,
            openalex_id=None,
            sources=[PaperSource.SEMANTIC_SCHOLAR],
            landing_page_url=MetadataNormalizer.normalize_url(
                cls._optional_string(record.get("url"))
            ),
            pdf_url=pdf_url,
            citation_count=record.get("citationCount"),
            full_text_status=(
                FullTextStatus.AVAILABLE if pdf_url else FullTextStatus.UNKNOWN
            ),
            relevance_score=None,
            selection_reason=None,
        )

    @staticmethod
    def _clean_text(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join(value.split())

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None
