"""Small client for the official arXiv Atom API."""

import re
import socket
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paperpilot.domain import PaperCandidate

from .mapper import ArxivMapper


class ArxivConfig(BaseModel):
    """Network and result-limit configuration for the arXiv adapter."""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    default_max_results: int = Field(default=10, ge=1, le=100)
    request_interval_seconds: float = Field(default=3.0, ge=0.0, le=30.0)
    max_attempts: int = Field(default=2, ge=1, le=3)
    user_agent: str = "PaperPilotAI/0.1 (paper research client)"

    @field_validator("user_agent")
    @classmethod
    def validate_user_agent(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_agent must not be empty")
        return value


class ArxivClientError(RuntimeError):
    """Base exception for failures at the arXiv adapter boundary."""


class ArxivNetworkError(ArxivClientError):
    """Raised when the official arXiv API cannot be reached successfully."""


class ArxivInvalidResponseError(ArxivClientError):
    """Raised when arXiv returns malformed or unsupported Atom content."""


class ArxivClient:
    """Search the official arXiv API and return PaperPilot candidates."""

    API_URL = "https://export.arxiv.org/api/query"
    MAX_RESULTS_LIMIT = 100
    _ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
    _ARXIV_NAMESPACE = "http://arxiv.org/schemas/atom"
    _CJK_RE = re.compile(r"[\u3400-\u9fff]")
    _LATIN_KEYWORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#-]*")

    def __init__(
        self,
        config: ArxivConfig | None = None,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        self.config = config or ArxivConfig()
        self._opener = opener or urlopen
        self._sleeper = sleeper or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._request_lock = threading.Lock()
        self._last_request_started: float | None = None

    def search(
        self, query: str, max_results: int | None = None
    ) -> list[PaperCandidate]:
        """Search arXiv keywords and map the Atom feed to domain models."""

        normalized_query = " ".join(query.split())
        if not normalized_query:
            raise ValueError("query must not be empty")
        result_limit = (
            self.config.default_max_results if max_results is None else max_results
        )
        if not 1 <= result_limit <= self.MAX_RESULTS_LIMIT:
            raise ValueError(
                f"max_results must be between 1 and {self.MAX_RESULTS_LIMIT}"
            )

        request = Request(
            self._build_url(normalized_query, result_limit),
            headers={"User-Agent": self.config.user_agent, "Accept": "application/atom+xml"},
            method="GET",
        )
        payload = self._fetch_with_retry(request)
        entries = self._parse_feed(payload)

        candidates: list[PaperCandidate] = []
        for index, entry in enumerate(entries):
            try:
                candidates.append(ArxivMapper.map_entry(entry))
            except (TypeError, ValueError) as error:
                raise ArxivInvalidResponseError(
                    f"Invalid arXiv entry at index {index}: {error}"
                ) from error
        return candidates

    def _build_url(self, query: str, max_results: int) -> str:
        # Treat whitespace-separated input as keywords. Quoting the complete
        # user query turns it into an exact-phrase search and makes common
        # queries such as "YOLO SLAM" incorrectly return no results.
        terms = self._query_terms(query)
        search_query = " AND ".join(f'all:"{term}"' for term in terms)
        parameters = urlencode(
            {
                "search_query": search_query,
                "start": 0,
                "max_results": max_results,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        )
        return f"{self.API_URL}?{parameters}"

    @classmethod
    def _query_terms(cls, query: str) -> list[str]:
        """Return API-safe keywords, preserving ordinary whitespace queries.

        arXiv metadata is predominantly English. For a Chinese research question,
        retain embedded technical identifiers (for example YOLO and SLAM) instead
        of submitting the complete Chinese sentence as one exact phrase.
        """

        raw_terms = (
            cls._LATIN_KEYWORD_RE.findall(query)
            if cls._CJK_RE.search(query)
            else query.split()
        )
        terms: list[str] = []
        seen: set[str] = set()
        for term in raw_terms:
            folded = term.casefold()
            if folded not in seen:
                seen.add(folded)
                terms.append(term)
        return terms or [query]

    def _fetch_with_retry(self, request: Request) -> bytes:
        """Fetch with bounded retries while respecting arXiv's request rate."""

        last_error: ArxivNetworkError | None = None
        for attempt in range(self.config.max_attempts):
            self._respect_request_interval()
            try:
                return self._fetch(request)
            except ArxivNetworkError as error:
                last_error = error
                if attempt + 1 >= self.config.max_attempts:
                    raise
        assert last_error is not None
        raise last_error

    def _respect_request_interval(self) -> None:
        # The same client instance is shared by all planned queries. Serialize
        # request starts so concurrent tasks cannot exceed the configured rate.
        with self._request_lock:
            now = self._monotonic()
            if self._last_request_started is not None:
                remaining = (
                    self.config.request_interval_seconds
                    - (now - self._last_request_started)
                )
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._monotonic()
            self._last_request_started = now

    def _fetch(self, request: Request) -> bytes:
        try:
            with self._opener(
                request, timeout=self.config.timeout_seconds
            ) as response:
                status = getattr(response, "status", 200)
                if status < 200 or status >= 300:
                    raise ArxivNetworkError(
                        f"arXiv API returned unexpected HTTP status {status}"
                    )
                payload = response.read()
        except ArxivNetworkError:
            raise
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            raise ArxivNetworkError(f"Unable to reach arXiv API: {error}") from error

        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        if not isinstance(payload, bytes) or not payload.strip():
            raise ArxivInvalidResponseError("arXiv API returned an empty response")
        return payload

    def _parse_feed(self, payload: bytes) -> list[dict[str, Any]]:
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as error:
            raise ArxivInvalidResponseError(
                f"arXiv API returned malformed XML: {error}"
            ) from error

        expected_feed_tag = self._tag(self._ATOM_NAMESPACE, "feed")
        if root.tag != expected_feed_tag:
            raise ArxivInvalidResponseError("arXiv response is not an Atom feed")

        return [
            self._parse_entry(element)
            for element in root.findall(self._tag(self._ATOM_NAMESPACE, "entry"))
        ]

    def _parse_entry(self, element: ElementTree.Element) -> dict[str, Any]:
        links = [
            {
                "href": link.get("href"),
                "rel": link.get("rel"),
                "type": link.get("type"),
                "title": link.get("title"),
            }
            for link in element.findall(self._tag(self._ATOM_NAMESPACE, "link"))
        ]
        entry_id = self._element_text(element, self._ATOM_NAMESPACE, "id")
        landing_page_url = next(
            (
                link["href"]
                for link in links
                if link["href"] and link["rel"] == "alternate"
            ),
            entry_id,
        )
        pdf_url = next(
            (
                link["href"]
                for link in links
                if link["href"]
                and (
                    link["title"] == "pdf"
                    or link["type"] == "application/pdf"
                )
            ),
            None,
        )
        return {
            "id": entry_id,
            "arxiv_id": entry_id,
            "title": self._element_text(element, self._ATOM_NAMESPACE, "title"),
            "abstract": self._element_text(
                element, self._ATOM_NAMESPACE, "summary"
            ),
            "authors": [
                self._element_text(author, self._ATOM_NAMESPACE, "name")
                for author in element.findall(
                    self._tag(self._ATOM_NAMESPACE, "author")
                )
            ],
            "published": self._element_text(
                element, self._ATOM_NAMESPACE, "published"
            ),
            "updated": self._element_text(
                element, self._ATOM_NAMESPACE, "updated"
            ),
            "landing_page_url": landing_page_url,
            "pdf_url": pdf_url,
            "doi": self._element_text(element, self._ARXIV_NAMESPACE, "doi"),
            "venue": self._element_text(
                element, self._ARXIV_NAMESPACE, "journal_ref"
            ),
        }

    @classmethod
    def _element_text(
        cls, element: ElementTree.Element, namespace: str, name: str
    ) -> str | None:
        child = element.find(cls._tag(namespace, name))
        return child.text if child is not None else None

    @staticmethod
    def _tag(namespace: str, name: str) -> str:
        return f"{{{namespace}}}{name}"
