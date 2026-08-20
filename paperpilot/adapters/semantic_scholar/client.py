"""Client for the Semantic Scholar Academic Graph paper search API."""

import json
import re
import socket
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paperpilot.domain import PaperCandidate

from .mapper import SemanticScholarMapper


class SemanticScholarConfig(BaseModel):
    """Authentication and network settings for Semantic Scholar requests."""

    model_config = ConfigDict(extra="forbid")

    api_key: str | None = None
    timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    default_max_results: int = Field(default=10, ge=1, le=100)
    user_agent: str = "PaperPilot"

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("user_agent")
    @classmethod
    def validate_user_agent(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_agent must not be empty")
        return value


class SemanticScholarError(RuntimeError):
    """Base exception for the Semantic Scholar adapter boundary."""


class SemanticScholarNetworkError(SemanticScholarError):
    """Raised for HTTP, timeout, and connection failures."""


class SemanticScholarInvalidResponseError(SemanticScholarError):
    """Raised when a Graph API response cannot be parsed or mapped."""


class SemanticScholarClient:
    """Search Semantic Scholar and return normalized paper candidates."""

    API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
    MAX_RESULTS_LIMIT = 100
    RESPONSE_FIELDS = (
        "paperId",
        "title",
        "abstract",
        "authors",
        "year",
        "venue",
        "citationCount",
        "externalIds",
        "openAccessPdf",
        "url",
    )
    _CJK_RE = re.compile(r"[\u3400-\u9fff]")
    _LATIN_KEYWORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#-]*")

    def __init__(
        self,
        config: SemanticScholarConfig | None = None,
        opener: Callable[..., Any] | None = None,
    ):
        self.config = config or SemanticScholarConfig()
        self._opener = opener or urlopen

    def search(
        self, query: str, max_results: int | None = None
    ) -> list[PaperCandidate]:
        """Search the Graph API and map its first result page."""

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

        headers = {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
        }
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        request = Request(
            self._build_url(self._search_query(normalized_query), result_limit),
            headers=headers,
            method="GET",
        )
        response = self._fetch_json(request)
        raw_papers = response.get("data")
        if not isinstance(raw_papers, list):
            raise SemanticScholarInvalidResponseError(
                "Semantic Scholar response field 'data' must be a list"
            )

        papers: list[PaperCandidate] = []
        for index, raw_paper in enumerate(raw_papers):
            if not isinstance(raw_paper, Mapping):
                raise SemanticScholarInvalidResponseError(
                    f"Invalid Semantic Scholar paper at index {index}: expected object"
                )
            try:
                papers.append(SemanticScholarMapper.map_paper(raw_paper))
            except (TypeError, ValueError) as error:
                raise SemanticScholarInvalidResponseError(
                    f"Invalid Semantic Scholar paper at index {index}: {error}"
                ) from error
        return papers

    @classmethod
    def _search_query(cls, query: str) -> str:
        """Keep technical identifiers when the natural-language query is CJK.

        Semantic Scholar metadata is predominantly English. Sending an entire
        Chinese sentence makes otherwise valid searches such as a YOLO/SLAM
        review unnecessarily sparse, while embedded technical terms are useful.
        """

        if not cls._CJK_RE.search(query):
            return query
        terms: list[str] = []
        seen: set[str] = set()
        for term in cls._LATIN_KEYWORD_RE.findall(query):
            folded = term.casefold()
            if folded not in seen:
                seen.add(folded)
                terms.append(term)
        return " ".join(terms) or query

    def _build_url(self, query: str, max_results: int) -> str:
        parameters = urlencode(
            {
                "query": query,
                "limit": max_results,
                "fields": ",".join(self.RESPONSE_FIELDS),
            }
        )
        return f"{self.API_URL}?{parameters}"

    def _fetch_json(self, request: Request) -> dict[str, Any]:
        try:
            with self._opener(
                request, timeout=self.config.timeout_seconds
            ) as response:
                status = getattr(response, "status", 200)
                if status < 200 or status >= 300:
                    raise SemanticScholarNetworkError(
                        "Semantic Scholar API returned unexpected "
                        f"HTTP status {status}"
                    )
                payload = response.read()
        except SemanticScholarNetworkError:
            raise
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            raise SemanticScholarNetworkError(
                f"Unable to reach Semantic Scholar API: {error}"
            ) from error

        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise SemanticScholarInvalidResponseError(
                    "Semantic Scholar response is not valid UTF-8"
                ) from error
        if not isinstance(payload, str) or not payload.strip():
            raise SemanticScholarInvalidResponseError(
                "Semantic Scholar API returned an empty response"
            )
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as error:
            raise SemanticScholarInvalidResponseError(
                f"Semantic Scholar API returned invalid JSON: {error}"
            ) from error
        if not isinstance(decoded, dict):
            raise SemanticScholarInvalidResponseError(
                "Semantic Scholar response root must be an object"
            )
        return decoded
