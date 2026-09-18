"""OpenAlex adapter: journal coverage without credentials."""

import json
from contextlib import contextmanager
from urllib.error import URLError

import pytest
from paperguide.adapters import (
    OpenAlexClient,
    OpenAlexConfig,
    OpenAlexInvalidResponseError,
    OpenAlexMapper,
    OpenAlexNetworkError,
    RetrieverProtocol,
)
from paperguide.domain import FullTextStatus, PaperSource

WORK = {
    "id": "https://openalex.org/W2001234567",
    "doi": "https://doi.org/10.1122/1.549709",
    "title": "Yield Stress Measurement for Concentrated Suspensions",
    "publication_year": 1983,
    "publication_date": "1983-04-01",
    "cited_by_count": 792,
    "authorships": [{"author": {"display_name": "Q. D. Nguyen"}}],
    "primary_location": {"source": {"display_name": "Journal of Rheology"}},
    "open_access": {"is_oa": False, "oa_url": None},
    "best_oa_location": {},
    "abstract_inverted_index": {"yield": [0, 3], "stress": [1], "of": [2]},
}


def _opener(payload: bytes, *, error: Exception | None = None):
    @contextmanager
    def open_url(request, timeout=None):
        if error is not None:
            raise error

        class _Response:
            def read(self):
                return payload

        yield _Response()

    return open_url


def make_client(payload: dict | bytes, *, error: Exception | None = None) -> OpenAlexClient:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return OpenAlexClient(
        OpenAlexConfig(request_interval_seconds=0.0),
        opener=_opener(raw, error=error),
    )


def test_client_satisfies_the_retriever_protocol():
    assert isinstance(make_client({"results": []}), RetrieverProtocol)


def test_a_journal_record_maps_to_a_candidate_with_provenance():
    papers = make_client({"results": [WORK]}).search("yield stress", 5)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.title.startswith("Yield Stress Measurement")
    assert paper.doi == "10.1122/1.549709"
    assert paper.openalex_id == "W2001234567"
    assert paper.venue == "Journal of Rheology"
    assert paper.publication_year == 1983
    assert paper.citation_count == 792
    assert paper.sources == [PaperSource.OPENALEX]


def test_a_paywalled_record_is_marked_unavailable_rather_than_unknown():
    """The pipeline can then ask for a manual upload instead of reasoning
    without the full text."""

    paper = OpenAlexMapper.map_work(WORK)

    assert paper.pdf_url is None
    assert paper.full_text_status is FullTextStatus.UNAVAILABLE


def test_an_open_access_record_carries_its_pdf():
    work = {**WORK, "best_oa_location": {"pdf_url": "https://example.org/paper.pdf"}}

    paper = OpenAlexMapper.map_work(work)

    assert paper.pdf_url == "https://example.org/paper.pdf"
    assert paper.full_text_status is FullTextStatus.AVAILABLE


def test_the_inverted_abstract_is_rebuilt_in_word_order():
    """OpenAlex publishes word positions rather than abstract text."""

    paper = OpenAlexMapper.map_work(WORK)

    assert paper.abstract == "yield stress of yield"


def test_a_missing_abstract_index_is_not_an_error():
    paper = OpenAlexMapper.map_work({**WORK, "abstract_inverted_index": None})

    assert paper.abstract is None


def test_one_unusable_record_does_not_discard_the_page():
    papers = make_client({"results": [{"id": "x", "title": ""}, WORK]}).search("q", 5)

    assert len(papers) == 1


def test_a_response_without_results_is_reported_as_invalid():
    with pytest.raises(OpenAlexInvalidResponseError):
        make_client({"meta": {}}).search("q", 5)


def test_malformed_json_is_reported_as_invalid():
    with pytest.raises(OpenAlexInvalidResponseError):
        make_client(b"not json").search("q", 5)


def test_an_unreachable_api_raises_a_network_error():
    with pytest.raises(OpenAlexNetworkError):
        make_client({"results": []}, error=URLError("down")).search("q", 5)


def test_a_contact_address_is_sent_only_when_configured():
    """Supplying it is what grants OpenAlex's higher polite-pool rate limit."""

    anonymous = OpenAlexClient(OpenAlexConfig())
    polite = OpenAlexClient(OpenAlexConfig(mailto="someone@example.org"))

    assert "mailto" not in anonymous._build_url("q", 5)
    assert "mailto=someone%40example.org" in polite._build_url("q", 5)


def test_an_empty_query_is_rejected_before_any_request():
    with pytest.raises(ValueError):
        make_client({"results": []}).search("   ", 5)
