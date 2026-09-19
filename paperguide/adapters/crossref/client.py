"""Client for the Crossref works API.

Crossref is the DOI registry itself, so it indexes essentially every journal
article that has a DOI, including the paywalled ones arXiv never sees. It
needs no key and no registration, and supplying a contact address moves the
caller into the polite pool.

It is the source that stays answerable when the others do not. arXiv signals
throttling with 406 and Semantic Scholar with 429, and both can refuse for
long stretches; a run that has Crossref still has a journal source.

Only registered metadata is retrieved, never a file, so every record is mapped
with ``full_text_status=UNAVAILABLE``. That is honest rather than limiting: the
DOI is what the evaluation matches on, and the full text comes from another
source's link or a manual upload.
"""

import json
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paperguide.domain import PaperCandidate, PaperSource

from .mapper import CrossrefMapper

#: Only records that are themselves papers. An unfiltered search returns
#: ``component`` records — a figure or a supplementary file deposited under
#: its own DOI — which carry the parent's title and a DOI that resolves to an
#: attachment. Measured on one query, six of ten results were components.
_ARTICLE_TYPES = ("journal-article", "proceedings-article")


class CrossrefConfig(BaseModel):
    """Network and result-limit configuration for the Crossref adapter."""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    default_max_results: int = Field(default=10, ge=1, le=100)
    request_interval_seconds: float = Field(default=0.2, ge=0.0, le=30.0)
    max_attempts: int = Field(default=2, ge=1, le=3)
    user_agent: str = "PaperGuideAI/0.1 (paper research client)"
    #: Crossref asks callers to identify themselves; doing so is what grants
    #: the polite pool's higher rate limit.
    mailto: str | None = None

    @field_validator("user_agent")
    @classmethod
    def validate_user_agent(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_agent must not be empty")
        return value


class CrossrefError(RuntimeError):
    """Base exception for failures at the Crossref adapter boundary."""


class CrossrefNetworkError(CrossrefError):
    """Raised when the Crossref API cannot be reached successfully."""


class CrossrefInvalidResponseError(CrossrefError):
    """Raised when Crossref returns content that is not a work list."""


class CrossrefClient:
    """Search Crossref and return PaperGuide candidates."""

    API_URL = "https://api.crossref.org/works"
    MAX_RESULTS_LIMIT = 100
    source = PaperSource.CROSSREF

    def __init__(
        self,
        config: CrossrefConfig | None = None,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        self.config = config or CrossrefConfig()
        self._opener = opener or urlopen
        self._sleeper = sleeper or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._request_lock = threading.Lock()
        self._last_request_started: float | None = None

    def search(self, query: str, max_results: int | None = None) -> list[PaperCandidate]:
        """Search Crossref works and map them to domain candidates."""

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
            headers={
                "User-Agent": self._request_user_agent(),
                "Accept": "application/json",
            },
            method="GET",
        )
        payload = self._fetch_with_retry(request)
        works = self._parse(payload)

        candidates: list[PaperCandidate] = []
        for work in works:
            try:
                candidates.append(CrossrefMapper.map_work(work))
            except (TypeError, ValueError):
                # One unusable record must not discard the rest of the page.
                continue
        return candidates

    def _request_user_agent(self) -> str:
        """Crossref reads the contact address from the User-Agent as well."""

        if not self.config.mailto:
            return self.config.user_agent
        return f"{self.config.user_agent} (mailto:{self.config.mailto})"

    def _build_url(self, query: str, max_results: int) -> str:
        parameters: dict[str, Any] = {
            "query.bibliographic": query,
            "rows": max_results,
            # Asking for the fields used keeps a response that would otherwise
            # carry every reference of every work down to a readable size.
            "select": ",".join(
                (
                    "DOI",
                    "title",
                    "author",
                    "container-title",
                    "abstract",
                    "URL",
                    "type",
                    "is-referenced-by-count",
                    "published-print",
                    "published-online",
                    "published",
                    "issued",
                )
            ),
            "filter": ",".join(f"type:{name}" for name in _ARTICLE_TYPES),
        }
        if self.config.mailto:
            parameters["mailto"] = self.config.mailto
        return f"{self.API_URL}?{urlencode(parameters)}"

    @staticmethod
    def _parse(payload: bytes) -> list[Any]:
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CrossrefInvalidResponseError(
                f"Crossref returned malformed JSON: {error}"
            ) from error
        message = document.get("message") if isinstance(document, dict) else None
        items = message.get("items") if isinstance(message, dict) else None
        if not isinstance(items, list):
            raise CrossrefInvalidResponseError("Crossref response has no items list")
        return items

    def _fetch_with_retry(self, request: Request) -> bytes:
        last_error: CrossrefNetworkError | None = None
        for attempt in range(self.config.max_attempts):
            self._respect_request_interval()
            try:
                return self._fetch(request)
            except CrossrefNetworkError as error:
                last_error = error
                if attempt + 1 >= self.config.max_attempts:
                    raise
        assert last_error is not None
        raise last_error

    def _respect_request_interval(self) -> None:
        with self._request_lock:
            now = self._monotonic()
            if self._last_request_started is not None:
                remaining = self.config.request_interval_seconds - (
                    now - self._last_request_started
                )
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._monotonic()
            self._last_request_started = now

    def _fetch(self, request: Request) -> bytes:
        try:
            with self._opener(request, timeout=self.config.timeout_seconds) as response:
                return response.read()
        except URLError as error:
            raise CrossrefNetworkError(
                f"Unable to reach Crossref API: {getattr(error, 'reason', error)}"
            ) from error
        except OSError as error:
            raise CrossrefNetworkError(f"Unable to reach Crossref API: {error}") from error
