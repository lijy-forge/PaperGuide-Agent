"""Unit tests for the PaperGuide arXiv adapter without network access."""

import copy
import socket
import unittest
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from paperguide.adapters.arxiv import (
    ArxivClient,
    ArxivConfig,
    ArxivInvalidResponseError,
    ArxivMapper,
    ArxivNetworkError,
)
from paperguide.domain import FullTextStatus, PaperSource


ARXIV_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>arXiv Query Results</title>
  <entry>
    <id>http://arxiv.org/abs/2401.12345v2</id>
    <updated>2025-02-03T10:30:00Z</updated>
    <published>2024-01-20T09:00:00Z</published>
    <title>  YOLO-SLAM:   Semantic_Mapping!  </title>
    <summary>
      A method combining object detection with semantic SLAM.
    </summary>
    <author><name>Smith, John</name></author>
    <author><name>\xe5\xbc\xa0\xe4\xbc\x9f</name></author>
    <link href="http://arxiv.org/abs/2401.12345v2" rel="alternate"
          type="text/html" />
    <link title="pdf" href="http://arxiv.org/pdf/2401.12345v2"
          rel="related" type="application/pdf" />
    <arxiv:doi>10.1000/YOLO-SLAM</arxiv:doi>
    <arxiv:journal_ref>ICRA 2025</arxiv:journal_ref>
  </entry>
</feed>
"""

EMPTY_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Query Results</title>
</feed>
"""


class MockResponse:
    """Minimal context-managed HTTP response used by adapter tests."""

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
    """Record request properties and return a predefined response."""

    def __init__(self, payload: bytes, status: int = 200):
        self.payload = payload
        self.status = status
        self.request = None
        self.timeout = None

    def __call__(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return MockResponse(self.payload, self.status)


class TestArxivAdapter(unittest.TestCase):
    def test_atom_response_is_parsed_into_candidate(self):
        client = ArxivClient(opener=RecordingOpener(ARXIV_FEED))

        papers = client.search("YOLO SLAM", max_results=5)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].title, "YOLO-SLAM: Semantic_Mapping!")
        self.assertEqual(papers[0].publication_year, 2024)
        self.assertEqual(papers[0].published_at.isoformat(), "2024-01-20T09:00:00+00:00")
        self.assertEqual(papers[0].updated_at.isoformat(), "2025-02-03T10:30:00+00:00")

    def test_title_is_normalized(self):
        paper = ArxivClient(opener=RecordingOpener(ARXIV_FEED)).search("SLAM")[0]

        self.assertEqual(paper.normalized_title, "yolo slam semantic mapping")

    def test_authors_are_mapped_and_normalized(self):
        paper = ArxivClient(opener=RecordingOpener(ARXIV_FEED)).search("SLAM")[0]

        self.assertEqual([author.full_name for author in paper.authors], ["Smith, John", "张伟"])
        self.assertEqual(
            [author.normalized_name for author in paper.authors],
            ["john smith", "张伟"],
        )

    def test_arxiv_id_and_urls_are_normalized(self):
        paper = ArxivClient(opener=RecordingOpener(ARXIV_FEED)).search("SLAM")[0]

        self.assertEqual(paper.arxiv_id, "2401.12345")
        self.assertEqual(paper.landing_page_url, "https://arxiv.org/abs/2401.12345")
        self.assertEqual(paper.pdf_url, "https://arxiv.org/pdf/2401.12345.pdf")

    def test_source_and_full_text_status_are_set(self):
        paper = ArxivClient(opener=RecordingOpener(ARXIV_FEED)).search("SLAM")[0]

        self.assertEqual(paper.sources, [PaperSource.ARXIV])
        self.assertIs(paper.full_text_status, FullTextStatus.AVAILABLE)

    def test_config_controls_request_without_hard_coding(self):
        opener = RecordingOpener(EMPTY_FEED)
        config = ArxivConfig(
            timeout_seconds=7.5,
            default_max_results=4,
            user_agent="PaperGuide-Test/1.0",
        )
        client = ArxivClient(config=config, opener=opener)

        client.search("YOLO SLAM")

        query = parse_qs(urlsplit(opener.request.full_url).query)
        self.assertEqual(query["max_results"], ["4"])
        self.assertEqual(query["search_query"], ['all:"YOLO" AND all:"SLAM"'])
        self.assertEqual(opener.request.get_header("User-agent"), "PaperGuide-Test/1.0")
        self.assertEqual(opener.timeout, 7.5)

    def test_multiple_queries_respect_official_request_interval(self):
        now = [100.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        client = ArxivClient(
            config=ArxivConfig(request_interval_seconds=3.0, max_attempts=1),
            opener=RecordingOpener(EMPTY_FEED),
            sleeper=sleep,
            monotonic=lambda: now[0],
        )

        client.search("visual SLAM")
        client.search("SLAM relocalization")

        self.assertEqual(sleeps, [3.0])

    def test_transient_network_failure_is_retried(self):
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise socket.timeout()
            return MockResponse(EMPTY_FEED)

        client = ArxivClient(
            config=ArxivConfig(request_interval_seconds=0.0, max_attempts=2),
            opener=opener,
        )

        self.assertEqual(client.search("SLAM"), [])
        self.assertEqual(len(calls), 2)

    def test_chinese_research_question_uses_embedded_technical_keywords(self):
        opener = RecordingOpener(EMPTY_FEED)

        ArxivClient(opener=opener).search(
            "分析2024-2026年YOLO与SLAM融合研究进展",
            max_results=1,
        )

        query = parse_qs(urlsplit(opener.request.full_url).query)
        self.assertEqual(query["search_query"], ['all:"YOLO" AND all:"SLAM"'])

    def test_invalid_response_raises_adapter_exception(self):
        malformed = ArxivClient(opener=RecordingOpener(b"<not-valid"))
        wrong_format = ArxivClient(opener=RecordingOpener(b"<response />"))

        with self.assertRaises(ArxivInvalidResponseError):
            malformed.search("SLAM")
        with self.assertRaises(ArxivInvalidResponseError):
            wrong_format.search("SLAM")

    def test_empty_feed_returns_empty_list(self):
        client = ArxivClient(opener=RecordingOpener(EMPTY_FEED))

        self.assertEqual(client.search("no matches"), [])

    def test_network_failures_raise_clear_adapter_exception(self):
        for network_error in (URLError("connection refused"), socket.timeout()):
            with self.subTest(error=type(network_error).__name__):
                client = ArxivClient(
                    opener=lambda request, timeout, error=network_error: (_ for _ in ()).throw(error)
                )
                with self.assertRaises(ArxivNetworkError) as context:
                    client.search("SLAM")
                self.assertIn("Unable to reach arXiv API", str(context.exception))

    def test_mapper_does_not_modify_input(self):
        raw_entry = {
            "id": "http://arxiv.org/abs/2401.12345v2",
            "arxiv_id": "arXiv:2401.12345v2",
            "title": " YOLO-SLAM ",
            "abstract": " Abstract ",
            "authors": ["Smith, John"],
            "published": "2024-01-20T09:00:00Z",
            "updated": "2025-02-03T10:30:00Z",
            "landing_page_url": "http://arxiv.org/abs/2401.12345v2",
            "pdf_url": None,
            "doi": None,
            "venue": None,
        }
        original = copy.deepcopy(raw_entry)

        paper = ArxivMapper.map_entry(raw_entry)

        self.assertEqual(raw_entry, original)
        self.assertIs(paper.full_text_status, FullTextStatus.UNKNOWN)

    def test_invalid_config_and_result_limit_are_rejected(self):
        with self.assertRaises(ValidationError):
            ArxivConfig(timeout_seconds=0)
        with self.assertRaises(ValidationError):
            ArxivConfig(max_attempts=0)
        with self.assertRaises(ValueError):
            ArxivClient(opener=RecordingOpener(EMPTY_FEED)).search(
                "SLAM", max_results=101
            )


if __name__ == "__main__":
    unittest.main()
