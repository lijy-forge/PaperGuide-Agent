"""Client for the OpenAlex works API.

arXiv indexes preprints, so a field that publishes in journals — rheology,
materials, most of engineering — is largely invisible through it. OpenAlex
indexes the journals themselves, including the paywalled ones, and needs no
API key or registration: supplying a contact address moves a caller into the
faster "polite pool", and omitting it is still allowed.

Only metadata is retrieved. A paywalled record carries no PDF, which the
mapper records as ``full_text_status=UNAVAILABLE`` so the pipeline can ask for
a manual upload rather than silently reasoning without the full text.
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

from .mapper import OpenAlexMapper


class OpenAlexConfig(BaseModel):
    """Network and result-limit configuration for the OpenAlex adapter."""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    default_max_results: int = Field(default=10, ge=1, le=200)
    request_interval_seconds: float = Field(default=0.2, ge=0.0, le=30.0)
    max_attempts: int = Field(default=2, ge=1, le=3)
    user_agent: str = "PaperGuideAI/0.1 (paper research client)"
    # OpenAlex asks callers to identify themselves; doing so is what grants
    # the polite pool's higher rate limit.
    mailto: str | None = None

    @field_validator("user_agent")
    @classmethod
    def validate_user_agent(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_agent must not be empty")
        return value


class OpenAlexError(RuntimeError):
    """Base exception for failures at the OpenAlex adapter boundary."""


class OpenAlexNetworkError(OpenAlexError):
    """Raised when the OpenAlex API cannot be reached successfully."""


class OpenAlexInvalidResponseError(OpenAlexError):
    """Raised when OpenAlex returns content that is not a work list."""


class OpenAlexClient:
    """Search OpenAlex and return PaperGuide candidates."""

    API_URL = "https://api.openalex.org/works"
    MAX_RESULTS_LIMIT = 200
    source = PaperSource.OPENALEX

    def __init__(
        self,
        config: OpenAlexConfig | None = None,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        self.config = config or OpenAlexConfig()
        self._opener = opener or urlopen
        self._sleeper = sleeper or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._request_lock = threading.Lock()
        self._last_request_started: float | None = None

    def search(self, query: str, max_results: int | None = None) -> list[PaperCandidate]:
        """Search OpenAlex works and map them to domain candidates."""

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
            headers={"User-Agent": self.config.user_agent, "Accept": "application/json"},
            method="GET",
        )
        payload = self._fetch_with_retry(request)
        works = self._parse(payload)

        candidates: list[PaperCandidate] = []
        for work in works:
            try:
                candidates.append(OpenAlexMapper.map_work(work))
            except (TypeError, ValueError):
                # One unusable record must not discard the rest of the page.
                continue
        return candidates

    def _build_url(self, query: str, max_results: int) -> str:
        parameters: dict[str, Any] = {
            "search": query,
            "per-page": max_results,
            "sort": "relevance_score:desc",
        }
        if self.config.mailto:
            parameters["mailto"] = self.config.mailto
        return f"{self.API_URL}?{urlencode(parameters)}"

    @staticmethod
    def _parse(payload: bytes) -> list[Any]:
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OpenAlexInvalidResponseError(
                f"OpenAlex returned malformed JSON: {error}"
            ) from error
        results = document.get("results") if isinstance(document, dict) else None
        if not isinstance(results, list):
            raise OpenAlexInvalidResponseError("OpenAlex response has no results list")
        return results

    def _fetch_with_retry(self, request: Request) -> bytes:
        last_error: OpenAlexNetworkError | None = None
        for attempt in range(self.config.max_attempts):
            self._respect_request_interval()
            try:
                return self._fetch(request)
            except OpenAlexNetworkError as error:
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
            raise OpenAlexNetworkError(
                f"Unable to reach OpenAlex API: {getattr(error, 'reason', error)}"
            ) from error
        except OSError as error:
            raise OpenAlexNetworkError(
                f"Unable to reach OpenAlex API: {error}"
            ) from error
