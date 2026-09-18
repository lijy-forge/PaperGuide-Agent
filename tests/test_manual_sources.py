"""Hybrid automatic retrieval plus manual-source upload contracts."""

import tempfile
import unittest
from pathlib import Path
from uuid import UUID

import pymupdf
from paperguide.document import PdfDownloader
from paperguide.domain import FullTextStatus, ManualPaperSource, PaperCandidate, PaperSource
from paperguide.orchestration.nodes.retriever import RetrieverNode
from paperguide.pipeline import SearchResult

from tests.api_fixtures import APITestRuntime


def valid_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Verified manual paper")
    payload = document.tobytes()
    document.close()
    return payload


class ManualSourceAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = APITestRuntime()

    def tearDown(self) -> None:
        self.runtime.close()

    def test_upload_and_task_payload_survive_broker_boundary(self) -> None:
        upload = self.runtime.client.post(
            "/api/v1/manual-sources",
            content=valid_pdf(),
            headers={"Content-Type": "application/pdf"},
        )
        self.assertEqual(upload.status_code, 201)
        body = upload.json()
        self.assertEqual(body["page_count"], 1)
        upload_id = UUID(body["upload_id"])
        self.assertTrue((self.runtime.artifact_root.parent / "manual-sources" / f"{upload_id}.pdf").is_file())

        submitted = self.runtime.client.post(
            "/api/v1/research",
            json={
                "question": "Compare real SLAM literature",
                "manual_sources": [{
                    "source": "cnki",
                    "title": "A Real CNKI Paper",
                    "source_url": "https://kns.cnki.net/example",
                    "upload_id": str(upload_id),
                    "authors": ["研究者"],
                    "publication_year": 2025,
                }],
            },
        )
        self.assertEqual(submitted.status_code, 202)
        queued = self.runtime.broker.claim_next(self.runtime.host_id)
        self.assertEqual(queued.request.manual_sources[0].source, PaperSource.CNKI)
        self.assertEqual(queued.request.manual_sources[0].upload_id, upload_id)

    def test_rejects_non_pdf_upload(self) -> None:
        response = self.runtime.client.post(
            "/api/v1/manual-sources",
            content=b"not a pdf",
            headers={"Content-Type": "application/pdf"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_PDF")


class ManualSourceDownloaderTests(unittest.TestCase):
    def test_controlled_upload_reference_is_ingested(self) -> None:
        upload_id = UUID("12345678-1234-5678-1234-567812345678")
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            manual_dir = root_path / "manual-sources"
            download_dir = root_path / "downloads"
            manual_dir.mkdir()
            payload = valid_pdf()
            (manual_dir / f"{upload_id}.pdf").write_bytes(payload)
            paper = PaperCandidate(
                title="Manual Paper",
                normalized_title="manual paper",
                authors=[],
                sources=[PaperSource.GOOGLE_SCHOLAR],
                landing_page_url="https://scholar.google.com/example",
                pdf_url=f"paperguide-upload://{upload_id}",
                full_text_status=FullTextStatus.AVAILABLE,
            )
            downloaded = PdfDownloader(
                download_dir, manual_source_dir=manual_dir
            ).download(paper)
            self.assertEqual(Path(downloaded.file_path).read_bytes(), payload)


class ManualSourceMergeTests(unittest.TestCase):
    def test_manual_pdf_enriches_matching_automatic_result_without_duplicate(self) -> None:
        automatic = PaperCandidate(
            title="Shared Paper",
            normalized_title="shared paper",
            authors=[],
            sources=[PaperSource.ARXIV],
            landing_page_url="https://arxiv.org/abs/1234.5678",
            pdf_url=None,
            full_text_status=FullTextStatus.UNAVAILABLE,
        )
        result = SearchResult(
            papers=[automatic],
            source_results={"arxiv": 1},
            source_errors={},
            warnings=[],
            total_found=1,
            total_after_dedup=1,
        )
        manual = ManualPaperSource(
            source=PaperSource.GOOGLE_SCHOLAR,
            title="Shared Paper",
            source_url="https://scholar.google.com/example",
            upload_id=UUID("12345678-1234-5678-1234-567812345678"),
        )
        merged = RetrieverNode._merge_manual_sources(result, [manual])
        self.assertEqual(len(merged.papers), 1)
        self.assertEqual(merged.papers[0].pdf_url, f"paperguide-upload://{manual.upload_id}")
        self.assertEqual(
            merged.papers[0].sources,
            [PaperSource.ARXIV, PaperSource.GOOGLE_SCHOLAR],
        )
        self.assertEqual(merged.papers[0].full_text_status, FullTextStatus.AVAILABLE)

if __name__ == "__main__":
    unittest.main()

class RetrievalOutageTests(unittest.TestCase):
    """Automatic discovery is a convenience, not a prerequisite.

    Every source can be unreachable — rate limited, blocked, offline — and a
    task that supplies its own papers has to keep going, because the papers
    worth reading are often paywalled and were never going to arrive from an
    API in the first place.
    """

    class _DeadPipeline:
        """Stands in for a search where no source answered."""

        def search(self, config):
            return SearchResult(
                papers=[],
                source_results={},
                source_errors={
                    "arxiv": "HTTP Error 406: Not Acceptable",
                    "openalex": "Too Many Requests",
                    "semantic_scholar": "HTTP Error 429:",
                },
                warnings=[],
                total_found=0,
                total_after_dedup=0,
            )

    @staticmethod
    def _state(manual_sources):
        from paperguide.domain import ResearchConfig
        from paperguide.orchestration import create_initial_state

        question = "多用户协作任务卸载与资源分配"
        return create_initial_state(
            question,
            ResearchConfig(
                question=question,
                max_papers=5,
                sources=[],
                manual_sources=manual_sources,
            ),
        )

    def _manual(self, title: str) -> ManualPaperSource:
        return ManualPaperSource(
            source=PaperSource.USER_UPLOAD,
            title=title,
            source_url="https://ieeexplore.ieee.org/document/8016573",
            upload_id=UUID("12345678-1234-5678-1234-567812345678"),
        )

    def test_uploaded_papers_carry_the_task_when_no_source_answers(self) -> None:
        node = RetrieverNode(self._DeadPipeline())

        state = node(self._state([self._manual("A Paywalled Offloading Paper")]))

        self.assertEqual([paper.title for paper in state["papers"]], ["A Paywalled Offloading Paper"])
        # The outage is still recorded rather than hidden by the rescue.
        self.assertTrue(state["search_result"].source_errors)
        self.assertFalse(state.get("errors"), "an answered task must not report a retrieval error")

    def test_an_outage_with_nothing_uploaded_is_reported_as_an_error(self) -> None:
        node = RetrieverNode(self._DeadPipeline())

        state = node(self._state([]))

        self.assertFalse(state["papers"])
        self.assertTrue(state.get("errors"), "an empty task must surface why retrieval produced nothing")


class ManualSourceProvenanceTests(unittest.TestCase):
    """A manual record must not be mistakable for a retrieved one."""

    @staticmethod
    def _make(source: PaperSource) -> ManualPaperSource:
        return ManualPaperSource(
            source=source,
            title="A Paywalled Paper",
            source_url="https://ieeexplore.ieee.org/document/8016573",
            upload_id=UUID("12345678-1234-5678-1234-567812345678"),
        )

    def test_a_publisher_the_system_never_searches_is_accepted(self) -> None:
        """Paywalled IEEE and Springer work is the case upload exists for."""

        for source in (PaperSource.USER_UPLOAD, PaperSource.GOOGLE_SCHOLAR, PaperSource.CNKI):
            self.assertEqual(self._make(source).source, source)

    def test_claiming_an_automatically_searched_source_is_rejected(self) -> None:
        """Otherwise an uploaded record is indistinguishable from a retrieved
        one, and provenance is the reason the field exists."""

        for source in (PaperSource.ARXIV, PaperSource.OPENALEX, PaperSource.SEMANTIC_SCHOLAR):
            with self.assertRaises(ValueError):
                self._make(source)
