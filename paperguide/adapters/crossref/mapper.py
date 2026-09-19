"""Map Crossref work records to PaperGuide candidates."""

import html
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from paperguide.domain import (
    Author,
    FullTextStatus,
    PaperCandidate,
    PaperSource,
)
from paperguide.services import MetadataNormalizer

#: Date fields in the order Crossref itself prefers. A record often carries
#: several, and an online-first article's print date can be a year later than
#: the one a reader would cite.
_DATE_FIELDS = ("published-print", "published-online", "published", "issued")

#: Crossref abstracts are deposited as JATS XML, so they arrive wrapped in
#: tags such as <jats:p>. The tags carry no information a reader or the
#: relevance gate needs, and left in place they become matchable text.
_MARKUP_RE = re.compile(r"<[^>]+>")


class CrossrefMapper:
    """Translate one Crossref work into the domain model."""

    @classmethod
    def map_work(cls, work: Mapping[str, Any]) -> PaperCandidate:
        title = cls._first_text(work.get("title"))
        if not title:
            raise ValueError("Crossref work has no title")

        doi = MetadataNormalizer.normalize_doi(cls._text(work.get("DOI")))
        landing = cls._text(work.get("URL")) or (
            f"https://doi.org/{doi}" if doi else ""
        )

        return PaperCandidate(
            title=title,
            normalized_title=MetadataNormalizer.normalize_title(title),
            abstract=cls._abstract(work.get("abstract")),
            authors=cls._authors(work.get("author")),
            publication_year=cls._year(work),
            published_at=cls._published_at(work),
            venue=cls._first_text(work.get("container-title")) or None,
            doi=doi,
            arxiv_id=None,
            semantic_scholar_id=None,
            openalex_id=None,
            sources=[PaperSource.CROSSREF],
            landing_page_url=MetadataNormalizer.normalize_url(landing),
            # Crossref indexes registered metadata, not files. It never points
            # at a PDF, so the pipeline treats every record as needing either
            # another source's link or a manual upload.
            pdf_url=None,
            citation_count=cls._non_negative(work.get("is-referenced-by-count")),
            full_text_status=FullTextStatus.UNAVAILABLE,
            relevance_score=None,
            selection_reason=None,
        )

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @classmethod
    def _first_text(cls, value: Any) -> str:
        """Crossref returns title and journal name as lists."""

        if isinstance(value, list):
            for item in value:
                text = cls._text(item)
                if text:
                    return text
            return ""
        return cls._text(value)

    @classmethod
    def _abstract(cls, value: Any) -> str | None:
        """Strip the JATS markup Crossref abstracts are wrapped in."""

        text = cls._text(value)
        if not text:
            return None
        cleaned = " ".join(html.unescape(_MARKUP_RE.sub(" ", text)).split())
        return cleaned or None

    @classmethod
    def _authors(cls, value: Any) -> list[Author]:
        if not isinstance(value, list):
            return []
        authors: list[Author] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            given = cls._text(item.get("given"))
            family = cls._text(item.get("family"))
            name = " ".join(part for part in (given, family) if part)
            # An organisation author has "name" instead of given/family.
            name = name or cls._text(item.get("name"))
            if name:
                authors.append(
                    Author(
                        full_name=name,
                        normalized_name=name.casefold(),
                        affiliations=[],
                    )
                )
        return authors

    @classmethod
    def _date_parts(cls, work: Mapping[str, Any]) -> list[int] | None:
        for field in _DATE_FIELDS:
            container = work.get(field)
            if not isinstance(container, Mapping):
                continue
            parts = container.get("date-parts")
            if not isinstance(parts, list) or not parts:
                continue
            first = parts[0]
            if isinstance(first, list) and first and isinstance(first[0], int):
                return [value for value in first if isinstance(value, int)]
        return None

    @classmethod
    def _year(cls, work: Mapping[str, Any]) -> int | None:
        parts = cls._date_parts(work)
        if not parts:
            return None
        year = parts[0]
        return year if 1 <= year <= 3000 else None

    @classmethod
    def _published_at(cls, work: Mapping[str, Any]) -> datetime | None:
        parts = cls._date_parts(work)
        if not parts:
            return None
        # A record may carry only a year, or a year and month. Filling the
        # missing components with 1 keeps the ordering the year already gives
        # without inventing a more precise date than was published.
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    @staticmethod
    def _non_negative(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if value >= 0 else None
