"""Map OpenAlex work records to PaperGuide candidates."""

from collections.abc import Mapping
from datetime import date
from typing import Any

from paperguide.domain import (
    Author,
    FullTextStatus,
    PaperCandidate,
    PaperSource,
)
from paperguide.services import MetadataNormalizer


class OpenAlexMapper:
    """Translate one OpenAlex work into the domain model."""

    @classmethod
    def map_work(cls, work: Mapping[str, Any]) -> PaperCandidate:
        title = cls._text(work.get("title") or work.get("display_name"))
        if not title:
            raise ValueError("OpenAlex work has no title")

        open_access = work.get("open_access") or {}
        best_location = work.get("best_oa_location") or {}
        pdf_url = MetadataNormalizer.normalize_url(
            cls._text(best_location.get("pdf_url")) or cls._text(open_access.get("oa_url"))
        )
        primary = (work.get("primary_location") or {}).get("source") or {}

        return PaperCandidate(
            title=title,
            normalized_title=MetadataNormalizer.normalize_title(title),
            abstract=cls._abstract(work.get("abstract_inverted_index")),
            authors=cls._authors(work.get("authorships")),
            publication_year=cls._year(work),
            published_at=cls._published_at(work.get("publication_date")),
            venue=cls._text(primary.get("display_name")) or None,
            doi=MetadataNormalizer.normalize_doi(cls._text(work.get("doi"))),
            arxiv_id=None,
            semantic_scholar_id=None,
            openalex_id=cls._openalex_id(work.get("id")),
            sources=[PaperSource.OPENALEX],
            landing_page_url=MetadataNormalizer.normalize_url(cls._text(work.get("id"))),
            pdf_url=pdf_url,
            citation_count=cls._non_negative(work.get("cited_by_count")),
            full_text_status=(
                FullTextStatus.AVAILABLE if pdf_url else FullTextStatus.UNAVAILABLE
            ),
            relevance_score=None,
            selection_reason=None,
        )

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @classmethod
    def _openalex_id(cls, value: Any) -> str | None:
        """Keep the bare work id, not the full URL it is served under."""

        text = cls._text(value)
        return text.rsplit("/", 1)[-1] or None if text else None

    @classmethod
    def _authors(cls, authorships: Any) -> list[Author]:
        authors: list[Author] = []
        if not isinstance(authorships, list):
            return authors
        for entry in authorships:
            if not isinstance(entry, Mapping):
                continue
            name = cls._text((entry.get("author") or {}).get("display_name"))
            if not name:
                continue
            authors.append(
                Author(full_name=name, normalized_name=name.casefold(), affiliations=[])
            )
        return authors

    @staticmethod
    def _abstract(inverted_index: Any) -> str | None:
        """Rebuild the abstract OpenAlex stores as a word to positions map.

        Licensing keeps OpenAlex from redistributing abstracts as plain text,
        so it publishes the positions of each word instead. Reversing that is
        lossless for the words, though the original spacing is gone.
        """

        if not isinstance(inverted_index, Mapping) or not inverted_index:
            return None
        positions: dict[int, str] = {}
        for word, places in inverted_index.items():
            if not isinstance(places, list):
                continue
            for place in places:
                if isinstance(place, int):
                    positions[place] = str(word)
        if not positions:
            return None
        return " ".join(positions[index] for index in sorted(positions)) or None

    @staticmethod
    def _year(work: Mapping[str, Any]) -> int | None:
        year = work.get("publication_year")
        return year if isinstance(year, int) and 1500 <= year <= 2200 else None

    @staticmethod
    def _published_at(value: Any) -> date | None:
        if not isinstance(value, str):
            return None
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None

    @staticmethod
    def _non_negative(value: Any) -> int | None:
        return value if isinstance(value, int) and value >= 0 else None
