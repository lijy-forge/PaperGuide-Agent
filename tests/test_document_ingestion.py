"""Unit tests for the deterministic PaperGuide document-ingestion pipeline."""

import tempfile
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from paperguide.document import (
    Document,
    DocumentIngestionPipeline,
    DocumentIngestionResult,
    DownloadedPDF,
    IngestionStatus,
    Page,
    PaperIngestionItem,
)
from paperguide.domain import Author, FullTextStatus, PaperCandidate, PaperSource
from pydantic import ValidationError


def make_paper(
    title: str,
    *,
    paper_id: UUID | None = None,
    pdf_url: str | None = None,
    status: FullTextStatus = FullTextStatus.AVAILABLE,
) -> PaperCandidate:
    return PaperCandidate(
        id=paper_id or uuid4(),
        title=title,
        normalized_title=title.casefold(),
        abstract=None,
        authors=[Author(full_name="Ada Researcher", affiliations=[])],
        publication_year=2026,
        venue=None,
        doi=None,
        arxiv_id=None,
        semantic_scholar_id=None,
        openalex_id=None,
        sources=[PaperSource.WEB],
        landing_page_url=None,
        pdf_url=pdf_url or f"https://example.com/{title.casefold()}.pdf",
        citation_count=None,
        full_text_status=status,
        relevance_score=None,
        selection_reason=None,
    )


def make_document(paper: PaperCandidate, path: str) -> Document:
    return Document(
        paper_id=paper.id,
        title=paper.title,
        source_path=path,
        pages=[Page(page_number=1, text=f"Text for {paper.title}")],
        sections=[],
        metadata={"page_count": 1},
    )


class MockDownloader:
    """Downloader writing deterministic bytes or raising per-title failures."""

    def __init__(
        self,
        directory: str,
        *,
        failures: set[str] | None = None,
        shared_content: bool = False,
    ):
        self.directory = Path(directory)
        self.failures = failures or set()
        self.shared_content = shared_content
        self.calls: list[UUID] = []

    def download(self, paper: PaperCandidate) -> DownloadedPDF:
        self.calls.append(paper.id)
        if paper.title in self.failures:
            raise RuntimeError(f"download failed for {paper.title}")
        payload = b"%PDF shared" if self.shared_content else f"%PDF {paper.id}".encode()
        path = self.directory / f"{paper.id}.pdf"
        path.write_bytes(payload)
        return DownloadedPDF(
            file_path=str(path), paper_id=paper.id, size_bytes=len(payload)
        )


class MockParser:
    """Parser returning one page or raising per-title failures."""

    def __init__(self, failures: set[str] | None = None):
        self.failures = failures or set()
        self.calls: list[UUID] = []

    def parse(self, file_path: str, paper: PaperCandidate) -> Document:
        self.calls.append(paper.id)
        if paper.title in self.failures:
            raise RuntimeError(f"cannot parse {file_path}")
        return make_document(paper, file_path)


class MockCleaner:
    """Cleaner recording calls and returning copied documents."""

    def __init__(self):
        self.calls: list[UUID] = []

    def clean(self, document: Document) -> Document:
        self.calls.append(document.paper_id)
        metadata = dict(document.metadata)
        metadata["cleaned"] = True
        return document.model_copy(update={"metadata": metadata}, deep=True)


class TestIngestionModels(unittest.TestCase):
    def test_parsed_item_accepts_matching_document(self):
        paper = make_paper("Model")
        document = make_document(paper, "paper.pdf")

        item = PaperIngestionItem(
            paper_id=paper.id,
            title=paper.title,
            status=IngestionStatus.PARSED,
            document=document,
            page_count=1,
        )

        self.assertEqual(item.document, document)

    def test_failed_item_requires_error_message(self):
        with self.assertRaises(ValidationError):
            PaperIngestionItem(
                paper_id=uuid4(), title="Failed", status=IngestionStatus.FAILED
            )

    def test_parsed_item_requires_document(self):
        with self.assertRaises(ValidationError):
            PaperIngestionItem(
                paper_id=uuid4(), title="Parsed", status=IngestionStatus.PARSED
            )

    def test_skipped_item_requires_explanation(self):
        with self.assertRaises(ValidationError):
            PaperIngestionItem(
                paper_id=uuid4(), title="Skipped", status=IngestionStatus.SKIPPED
            )

    def test_ingestion_result_json_round_trip(self):
        paper = make_paper("Round Trip")
        document = make_document(paper, "paper.pdf")
        item = PaperIngestionItem(
            paper_id=paper.id,
            title=paper.title,
            status=IngestionStatus.PARSED,
            document=document,
            page_count=1,
        )
        result = DocumentIngestionResult(
            items=[item],
            documents=[document],
            total_requested=1,
            total_eligible=1,
            total_downloaded=0,
            total_parsed=1,
            total_skipped=0,
            total_failed=0,
        )

        restored = DocumentIngestionResult.model_validate_json(result.model_dump_json())

        self.assertEqual(restored, result)

    def test_ingestion_result_rejects_inconsistent_statistics(self):
        skipped = PaperIngestionItem(
            paper_id=uuid4(),
            title="Skipped",
            status=IngestionStatus.SKIPPED,
            warnings=["No PDF"],
        )

        with self.assertRaises(ValidationError):
            DocumentIngestionResult(
                items=[skipped],
                documents=[],
                total_requested=1,
                total_eligible=1,
                total_downloaded=0,
                total_parsed=0,
                total_skipped=0,
                total_failed=0,
            )

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            PaperIngestionItem(
                paper_id=uuid4(),
                title="Skipped",
                status=IngestionStatus.SKIPPED,
                warnings=["Reason"],
                unknown=True,
            )


class TestDocumentIngestionPipeline(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def _pipeline(
        self,
        *,
        download_failures: set[str] | None = None,
        parse_failures: set[str] | None = None,
        shared_content: bool = False,
        cleaner=None,
    ):
        downloader = MockDownloader(
            self.directory.name,
            failures=download_failures,
            shared_content=shared_content,
        )
        parser = MockParser(parse_failures)
        return (
            DocumentIngestionPipeline(downloader, parser, cleaner),
            downloader,
            parser,
        )

    def test_multiple_papers_all_succeed(self):
        papers = [make_paper("One"), make_paper("Two")]
        pipeline, _, _ = self._pipeline()

        result = pipeline.ingest(papers)

        self.assertEqual(result.total_parsed, 2)
        self.assertEqual(len(result.documents), 2)
        self.assertTrue(all(item.status is IngestionStatus.PARSED for item in result.items))

    def test_missing_pdf_url_is_skipped(self):
        paper = make_paper("No URL")
        paper = paper.model_copy(update={"pdf_url": None})
        pipeline, downloader, _ = self._pipeline()

        result = pipeline.ingest([paper])

        self.assertEqual(result.items[0].status, IngestionStatus.SKIPPED)
        self.assertEqual(downloader.calls, [])

    def test_disallowed_full_text_status_is_skipped(self):
        paper = make_paper("Unavailable", status=FullTextStatus.UNAVAILABLE)
        pipeline, downloader, _ = self._pipeline()

        result = pipeline.ingest([paper])

        self.assertEqual(result.total_skipped, 1)
        self.assertEqual(downloader.calls, [])

    def test_unknown_status_with_pdf_url_is_eligible(self):
        paper = make_paper("Unknown", status=FullTextStatus.UNKNOWN)
        pipeline, _, _ = self._pipeline()

        result = pipeline.ingest([paper])

        self.assertEqual(result.total_eligible, 1)
        self.assertEqual(result.total_parsed, 1)

    def test_download_failure_does_not_stop_following_paper(self):
        papers = [make_paper("Broken"), make_paper("Good")]
        pipeline, _, _ = self._pipeline(download_failures={"Broken"})

        result = pipeline.ingest(papers)

        self.assertEqual(result.items[0].status, IngestionStatus.FAILED)
        self.assertEqual(result.items[0].error_stage, "download")
        self.assertEqual(result.items[1].status, IngestionStatus.PARSED)

    def test_download_error_message_redacts_sensitive_locations(self):
        paper = make_paper("Broken")

        class SensitiveDownloader:
            def download(self, candidate):
                raise RuntimeError(
                    "failed at C:\\Users\\researcher\\secret\\paper.pdf "
                    "from https://example.com/private.pdf"
                )

        pipeline = DocumentIngestionPipeline(SensitiveDownloader(), MockParser())

        item = pipeline.ingest([paper]).items[0]

        self.assertNotIn("C:\\Users", item.error_message or "")
        self.assertNotIn("https://", item.error_message or "")
        self.assertIn("paper.pdf", item.error_message or "")

    def test_parse_failure_does_not_stop_following_paper(self):
        papers = [make_paper("Broken"), make_paper("Good")]
        pipeline, _, _ = self._pipeline(parse_failures={"Broken"})

        result = pipeline.ingest(papers)

        self.assertEqual(result.items[0].error_stage, "parse")
        self.assertEqual(result.items[1].status, IngestionStatus.PARSED)

    def test_parse_failure_preserves_download_information(self):
        paper = make_paper("Broken")
        pipeline, _, _ = self._pipeline(parse_failures={"Broken"})

        item = pipeline.ingest([paper]).items[0]

        self.assertIsNotNone(item.downloaded_file_path)
        self.assertIsNotNone(item.content_hash)
        self.assertGreater(item.size_bytes or 0, 0)
        self.assertNotIn(self.directory.name, item.error_message or "")

    def test_duplicate_paper_id_is_processed_once(self):
        paper = make_paper("First")
        duplicate = paper.model_copy(update={"title": "Duplicate"})
        pipeline, downloader, parser = self._pipeline()

        result = pipeline.ingest([paper, duplicate])

        self.assertEqual(len(downloader.calls), 1)
        self.assertEqual(len(parser.calls), 1)
        self.assertEqual(result.items[1].status, IngestionStatus.SKIPPED)
        self.assertEqual(result.total_eligible, 1)

    def test_same_hash_for_different_papers_reuses_parsed_content(self):
        papers = [make_paper("One"), make_paper("Two")]
        pipeline, downloader, parser = self._pipeline(shared_content=True)

        result = pipeline.ingest(papers)

        self.assertEqual(len(downloader.calls), 2)
        self.assertEqual(len(parser.calls), 1)
        self.assertEqual(result.total_downloaded, 2)
        self.assertEqual(result.total_parsed, 2)
        self.assertEqual(result.documents[1].paper_id, papers[1].id)
        self.assertEqual(result.documents[1].title, papers[1].title)
        self.assertIsNot(result.documents[0], result.documents[1])
        self.assertTrue(result.items[1].warnings)

    def test_cleaner_is_called_when_configured(self):
        cleaner = MockCleaner()
        paper = make_paper("Clean")
        pipeline, _, _ = self._pipeline(cleaner=cleaner)

        result = pipeline.ingest([paper])

        self.assertEqual(cleaner.calls, [paper.id])
        self.assertTrue(result.documents[0].metadata["cleaned"])

    def test_pipeline_works_without_cleaner(self):
        pipeline, _, _ = self._pipeline()

        result = pipeline.ingest([make_paper("Raw")])

        self.assertNotIn("cleaned", result.documents[0].metadata)

    def test_inputs_are_not_modified(self):
        papers = [make_paper("One"), make_paper("Two")]
        list_ids = [id(paper) for paper in papers]
        before = [paper.model_dump(mode="json") for paper in papers]
        pipeline, _, _ = self._pipeline()

        pipeline.ingest(papers)

        self.assertEqual([paper.model_dump(mode="json") for paper in papers], before)
        self.assertEqual([id(paper) for paper in papers], list_ids)

    def test_output_order_matches_input_order(self):
        papers = [
            make_paper("First"),
            make_paper("Skip", status=FullTextStatus.FAILED),
            make_paper("Third"),
        ]
        pipeline, _, _ = self._pipeline()

        result = pipeline.ingest(papers)

        self.assertEqual([item.paper_id for item in result.items], [p.id for p in papers])

    def test_all_papers_can_be_skipped(self):
        papers = [
            make_paper("One", status=FullTextStatus.UNAVAILABLE),
            make_paper("Two", status=FullTextStatus.FAILED),
        ]
        pipeline, _, _ = self._pipeline()

        result = pipeline.ingest(papers)

        self.assertEqual(result.total_skipped, 2)
        self.assertEqual(result.total_eligible, 0)
        self.assertEqual(result.documents, [])

    def test_all_eligible_papers_can_fail(self):
        papers = [make_paper("One"), make_paper("Two")]
        pipeline, _, _ = self._pipeline(download_failures={"One", "Two"})

        result = pipeline.ingest(papers)

        self.assertEqual(result.total_failed, 2)
        self.assertEqual(result.total_eligible, 2)
        self.assertEqual(result.documents, [])

    def test_empty_input_returns_zero_statistics(self):
        pipeline, _, _ = self._pipeline()

        result = pipeline.ingest([])

        self.assertEqual(result.items, [])
        self.assertEqual(result.total_requested, 0)
        self.assertEqual(result.total_eligible, 0)
        self.assertEqual(result.total_downloaded, 0)
        self.assertEqual(result.total_parsed, 0)
        self.assertEqual(result.total_skipped, 0)
        self.assertEqual(result.total_failed, 0)

    def test_statistics_include_mixed_outcomes(self):
        good = make_paper("Good")
        failed = make_paper("Failed")
        skipped = make_paper("Skipped", status=FullTextStatus.UNAVAILABLE)
        duplicate = good.model_copy(update={"title": "Duplicate"})
        pipeline, _, _ = self._pipeline(download_failures={"Failed"})

        result = pipeline.ingest([good, failed, skipped, duplicate])

        self.assertEqual(result.total_requested, 4)
        self.assertEqual(result.total_eligible, 2)
        self.assertEqual(result.total_downloaded, 1)
        self.assertEqual(result.total_parsed, 1)
        self.assertEqual(result.total_skipped, 2)
        self.assertEqual(result.total_failed, 1)

    def test_batch_warnings_are_stably_deduplicated(self):
        papers = [
            make_paper("One", status=FullTextStatus.UNAVAILABLE),
            make_paper("Two", status=FullTextStatus.UNAVAILABLE),
            make_paper("Three"),
        ]
        duplicate = papers[2].model_copy(update={"title": "Duplicate"})
        pipeline, _, _ = self._pipeline()

        result = pipeline.ingest([papers[0], papers[1], papers[2], duplicate])

        self.assertEqual(
            result.warnings,
            [
                "Paper full-text status does not permit PDF ingestion.",
                "Duplicate paper_id in this batch; only the first item was processed.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
