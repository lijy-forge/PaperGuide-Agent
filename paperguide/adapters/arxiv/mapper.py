"""Map parsed arXiv Atom entries to PaperGuide domain models."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from paperguide.domain import Author, FullTextStatus, PaperCandidate, PaperSource
from paperguide.services import MetadataNormalizer


class ArxivMapper:
    """Convert a parsed, read-only arXiv entry into a paper candidate."""

    @classmethod
    def map_entry(cls, entry: Mapping[str, Any]) -> PaperCandidate:
        """Map one parsed Atom entry without mutating the source mapping."""

        title = cls._clean_text(entry.get("title"))
        if not title:
            raise ValueError("arXiv entry is missing a title")

        arxiv_id = MetadataNormalizer.normalize_arxiv_id(
            cls._optional_string(entry.get("arxiv_id"))
            or cls._optional_string(entry.get("id"))
        )
        if arxiv_id is None:
            raise ValueError("arXiv entry contains an invalid identifier")

        authors = [
            Author(
                full_name=name,
                normalized_name=MetadataNormalizer.normalize_author_name(name),
                affiliations=[],
            )
            for raw_name in entry.get("authors", [])
            if (name := cls._clean_text(raw_name))
        ]

        published_at = cls._parse_datetime(entry.get("published"), "published")
        updated_at = cls._parse_datetime(entry.get("updated"), "updated")
        landing_page_url = MetadataNormalizer.normalize_url(
            cls._optional_string(entry.get("landing_page_url"))
            or cls._optional_string(entry.get("id"))
        )
        pdf_url = MetadataNormalizer.normalize_url(
            cls._optional_string(entry.get("pdf_url"))
        )

        return PaperCandidate(
            title=title,
            normalized_title=MetadataNormalizer.normalize_title(title),
            abstract=cls._clean_text(entry.get("abstract")) or None,
            authors=authors,
            publication_year=published_at.year if published_at else None,
            published_at=published_at,
            updated_at=updated_at,
            venue=cls._clean_text(entry.get("venue")) or None,
            doi=MetadataNormalizer.normalize_doi(
                cls._optional_string(entry.get("doi"))
            ),
            arxiv_id=arxiv_id,
            semantic_scholar_id=None,
            openalex_id=None,
            sources=[PaperSource.ARXIV],
            landing_page_url=landing_page_url,
            pdf_url=pdf_url,
            citation_count=None,
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

    @classmethod
    def _parse_datetime(cls, value: Any, field_name: str) -> datetime | None:
        raw_value = cls._optional_string(value)
        if raw_value is None:
            return None
        try:
            return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"arXiv entry contains an invalid {field_name} date") from error
