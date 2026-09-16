"""Unit tests for the Semantic Scholar adapter and retriever protocol."""

import copy
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from paperguide.adapters import RetrieverProtocol
from paperguide.adapters.arxiv import ArxivClient
from paperguide.adapters.semantic_scholar import (
    SemanticScholarClient,
    SemanticScholarConfig,
    SemanticScholarInvalidResponseError,
    SemanticScholarMapper,
    SemanticScholarNetworkError,
)
from paperguide.domain import FullTextStatus, PaperSource

SEMANTIC_SCHOLAR_RESPONSE = {
    "total": 1,
    "offset": 0,
    "data": [
        {
            "paperId": "S2-PAPER-123",
            "title": "  YOLO-SLAM:   Semantic_Mapping!  ",
            "abstract": "A paper about semantic mapping and visual SLAM.",
            "authors": [
                {"authorId": "A1", "name": "Smith, John"},
                {"authorId": "A2", "name": "张伟"},
            ],
            "year": 2025,
            "venue": "ICRA",
            "citationCount": 42,
            "externalIds": {
                "DOI": "https://doi.org/10.1000/YOLO-SLAM",
                "ArXiv": "2401.12345v2",
            },
            "openAccessPdf": {
                "url": "https://arxiv.org/pdf/2401.12345v2.pdf",
                "status": "GREEN",
            },
            "url": "HTTPS://WWW.SemanticScholar.org/paper/S2-PAPER-123#details",
        }
    ],
}


class MockResponse:
    """Minimal context-managed JSON response used by adapter tests."""

    def __init__(self, payload: bytes, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


class RecordingOpener:
    """Record the outgoing request and return a predefined response."""

    def __init__(self, payload, status: int = 200):
        self.payload = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode("utf-8")
        )
        self.status = status
        self.request = None
        self.timeout = None

    def __call__(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return MockResponse(self.payload, self.status)


class TestSemanticScholarAdapter(unittest.TestCase):
    def test_api_response_is_parsed(self):
        client = SemanticScholarClient(
            opener=RecordingOpener(SEMANTIC_SCHOLAR_RESPONSE)
        )

        papers = client.search("YOLO SLAM", max_results=5)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].semantic_scholar_id, "S2-PAPER-123")
        self.assertEqual(papers[0].title, "YOLO-SLAM: Semantic_Mapping!")
        self.assertEqual(
            papers[0].normalized_title, "yolo slam semantic mapping"
        )

    def test_fields_are_mapped(self):
        paper = SemanticScholarClient(
            opener=RecordingOpener(SEMANTIC_SCHOLAR_RESPONSE)
        ).search("SLAM")[0]

        self.assertEqual(paper.abstract, SEMANTIC_SCHOLAR_RESPONSE["data"][0]["abstract"])
        self.assertEqual(paper.publication_year, 2025)
        self.assertEqual(paper.venue, "ICRA")
        self.assertEqual(
            paper.landing_page_url,
            "https://www.semanticscholar.org/paper/S2-PAPER-123",
        )
        self.assertEqual(paper.sources, [PaperSource.SEMANTIC_SCHOLAR])

    def test_authors_are_converted(self):
        paper = SemanticScholarClient(
            opener=RecordingOpener(SEMANTIC_SCHOLAR_RESPONSE)
        ).search("SLAM")[0]

        self.assertEqual(
            [author.full_name for author in paper.authors],
            ["Smith, John", "张伟"],
        )
        self.assertEqual(
            [author.normalized_name for author in paper.authors],
            ["john smith", "张伟"],
        )

    def test_doi_and_arxiv_id_are_normalized(self):
        paper = SemanticScholarClient(
            opener=RecordingOpener(SEMANTIC_SCHOLAR_RESPONSE)
        ).search("SLAM")[0]

        self.assertEqual(paper.doi, "10.1000/yolo-slam")
        self.assertEqual(paper.arxiv_id, "2401.12345")

    def test_citation_count_is_preserved(self):
        paper = SemanticScholarClient(
            opener=RecordingOpener(SEMANTIC_SCHOLAR_RESPONSE)
        ).search("SLAM")[0]

        self.assertEqual(paper.citation_count, 42)

    def test_open_access_pdf_is_preserved(self):
        paper = SemanticScholarClient(
            opener=RecordingOpener(SEMANTIC_SCHOLAR_RESPONSE)
        ).search("SLAM")[0]

        self.assertEqual(
            paper.pdf_url, "https://arxiv.org/pdf/2401.12345.pdf"
        )
        self.assertIs(paper.full_text_status, FullTextStatus.AVAILABLE)

    def test_empty_results_return_empty_list(self):
        client = SemanticScholarClient(opener=RecordingOpener({"data": []}))

        self.assertEqual(client.search("no matches"), [])

    def test_chinese_query_uses_embedded_technical_keywords(self):
        opener = RecordingOpener({"data": []})

        SemanticScholarClient(opener=opener).search(
            "分析2024-2026年YOLO与SLAM融合研究进展"
        )

        query = parse_qs(urlsplit(opener.request.full_url).query)
        self.assertEqual(query["query"], ["YOLO SLAM"])

    def test_http_error_is_wrapped(self):
        client = SemanticScholarClient(
            opener=RecordingOpener({"message": "rate limited"}, status=429)
        )

        with self.assertRaises(SemanticScholarNetworkError) as context:
            client.search("SLAM")

        self.assertIn("HTTP status 429", str(context.exception))

    def test_timeout_is_wrapped(self):
        def raise_timeout(request, timeout):
            raise TimeoutError("timed out")

        client = SemanticScholarClient(opener=raise_timeout)

        with self.assertRaises(SemanticScholarNetworkError) as context:
            client.search("SLAM")

        self.assertIn("Unable to reach Semantic Scholar API", str(context.exception))

    def test_invalid_json_is_rejected(self):
        client = SemanticScholarClient(opener=RecordingOpener(b"{not-json"))

        with self.assertRaises(SemanticScholarInvalidResponseError):
            client.search("SLAM")

    def test_protocol_compatibility(self):
        arxiv_client = ArxivClient()
        semantic_scholar_client = SemanticScholarClient()

        self.assertIsInstance(arxiv_client, RetrieverProtocol)
        self.assertIsInstance(semantic_scholar_client, RetrieverProtocol)

    def test_mapper_does_not_modify_input(self):
        raw_record = copy.deepcopy(SEMANTIC_SCHOLAR_RESPONSE["data"][0])
        original = copy.deepcopy(raw_record)

        SemanticScholarMapper.map_paper(raw_record)

        self.assertEqual(raw_record, original)

    def test_api_key_is_optional_and_request_fields_are_explicit(self):
        without_key = RecordingOpener({"data": []})
        SemanticScholarClient(opener=without_key).search("YOLO SLAM")
        headers_without_key = {
            key.casefold(): value for key, value in without_key.request.header_items()
        }
        self.assertNotIn("x-api-key", headers_without_key)

        with_key = RecordingOpener({"data": []})
        config = SemanticScholarConfig(
            api_key=" secret-key ",
            timeout_seconds=8,
            default_max_results=3,
            user_agent="PaperGuide-Test",
        )
        SemanticScholarClient(config=config, opener=with_key).search("YOLO SLAM")
        headers_with_key = {
            key.casefold(): value for key, value in with_key.request.header_items()
        }
        query = parse_qs(urlsplit(with_key.request.full_url).query)

        self.assertEqual(headers_with_key["x-api-key"], "secret-key")
        self.assertEqual(headers_with_key["user-agent"], "PaperGuide-Test")
        self.assertEqual(query["limit"], ["3"])
        self.assertEqual(query["query"], ["YOLO SLAM"])
        self.assertEqual(
            query["fields"][0],
            ",".join(SemanticScholarClient.RESPONSE_FIELDS),
        )
        self.assertEqual(with_key.timeout, 8)


if __name__ == "__main__":
    unittest.main()
