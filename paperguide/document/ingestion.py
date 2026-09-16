"""Deterministic batch pipeline from paper candidates to documents."""

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from uuid import UUID, uuid4

from paperguide.domain import FullTextStatus, PaperCandidate
from paperguide.services import MetadataNormalizer

from .cleaning import DocumentTextCleaner
from .downloader import PdfDownloader
from .hashing import calculate_sha256
from .ingestion_models import (
    DocumentIngestionResult,
    IngestionStatus,
    PaperIngestionItem,
)
from .models import Document
from .parser import PdfParser


class DocumentIngestionPipeline:
    """Download and parse papers in stable order with per-paper isolation."""

    _ALLOWED_FULL_TEXT_STATUSES = frozenset(
        {FullTextStatus.AVAILABLE, FullTextStatus.UNKNOWN}
    )
    _URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
    _WINDOWS_PATH_RE = re.compile(
        r"(?<!\w)[A-Za-z]:[\\/](?:[^\\/\s]+[\\/])*([^\\/\s]+)"
    )
    _POSIX_PATH_RE = re.compile(r"(?<!\w)/(?:[^/\s]+/)+([^/\s]+)")

    def __init__(
        self,
        downloader: PdfDownloader,
        parser: PdfParser,
        cleaner: DocumentTextCleaner | None = None,
    ):
        self.downloader = downloader
        self.parser = parser
        self.cleaner = cleaner

    def ingest(
        self,
        papers: list[PaperCandidate],
        *,
        item_observer: Callable[[int, int, int, int, str], None] | None = None,
    ) -> DocumentIngestionResult:
        """Ingest a batch without mutating its list or paper candidates."""

        items: list[PaperIngestionItem] = []
        seen_paper_ids: set[UUID] = set()
        documents_by_hash: dict[str, Document] = {}
        total_eligible = 0
        total_downloaded = 0

        def observe(title: str) -> None:
            if item_observer is None:
                return
            succeeded = sum(item.status is IngestionStatus.PARSED for item in items)
            failed = sum(item.status is IngestionStatus.FAILED for item in items)
            skipped = sum(item.status is IngestionStatus.SKIPPED for item in items)
            try:
                item_observer(len(items), succeeded, failed, skipped, title)
            except Exception:
                # Telemetry cannot affect deterministic ingestion results.
                return

        for paper in papers:
            if paper.id in seen_paper_ids:
                items.append(
                    self._skipped_item(
                        paper,
                        "Duplicate paper_id in this batch; only the first item was processed.",
                    )
                )
                observe(paper.title)
                continue
            seen_paper_ids.add(paper.id)

            skip_reason = self._ineligible_reason(paper)
            if skip_reason is not None:
                items.append(self._skipped_item(paper, skip_reason))
                observe(paper.title)
                continue

            total_eligible += 1
            try:
                downloaded = self.downloader.download(paper)
            except Exception as error:
                items.append(self._failed_item(paper, "download", error))
                observe(paper.title)
                continue

            total_downloaded += 1
            try:
                content_hash = calculate_sha256(downloaded.file_path)
            except Exception as error:
                items.append(
                    self._failed_item(
                        paper,
                        "hash",
                        error,
                        downloaded_file_path=downloaded.file_path,
                        size_bytes=downloaded.size_bytes,
                    )
                )
                observe(paper.title)
                continue

            cached_document = documents_by_hash.get(content_hash)
            if cached_document is not None:
                document = self._reuse_document(cached_document, paper, downloaded.file_path)
                items.append(
                    self._parsed_item(
                        paper,
                        document,
                        downloaded.file_path,
                        downloaded.size_bytes,
                        content_hash,
                        [
                            "Duplicate PDF content in this batch; reused the first "
                            "parsed document."
                        ],
                    )
                )
                observe(paper.title)
                continue

            try:
                document = self.parser.parse(downloaded.file_path, paper)
            except Exception as error:
                items.append(
                    self._failed_item(
                        paper,
                        "parse",
                        error,
                        downloaded_file_path=downloaded.file_path,
                        content_hash=content_hash,
                        size_bytes=downloaded.size_bytes,
                    )
                )
                observe(paper.title)
                continue

            if self.cleaner is not None:
                try:
                    document = self.cleaner.clean(document)
                except Exception as error:
                    items.append(
                        self._failed_item(
                            paper,
                            "clean",
                            error,
                            downloaded_file_path=downloaded.file_path,
                            content_hash=content_hash,
                            size_bytes=downloaded.size_bytes,
                        )
                    )
                    observe(paper.title)
                    continue

            item_warnings = list(document.metadata.get("cleaning_warnings", []))
            documents_by_hash[content_hash] = document
            items.append(
                self._parsed_item(
                    paper,
                    document,
                    downloaded.file_path,
                    downloaded.size_bytes,
                    content_hash,
                    item_warnings,
                )
            )
            observe(paper.title)

        documents = [
            item.document
            for item in items
            if item.status is IngestionStatus.PARSED and item.document is not None
        ]
        warnings = self._stable_unique(
            warning for item in items for warning in item.warnings
        )
        return DocumentIngestionResult(
            items=items,
            documents=documents,
            total_requested=len(papers),
            total_eligible=total_eligible,
            total_downloaded=total_downloaded,
            total_parsed=len(documents),
            total_skipped=sum(
                item.status is IngestionStatus.SKIPPED for item in items
            ),
            total_failed=sum(item.status is IngestionStatus.FAILED for item in items),
            warnings=warnings,
        )

    @classmethod
    def _ineligible_reason(cls, paper: PaperCandidate) -> str | None:
        if paper.full_text_status not in cls._ALLOWED_FULL_TEXT_STATUSES:
            return "Paper full-text status does not permit PDF ingestion."
        if MetadataNormalizer.normalize_url(paper.pdf_url) is None:
            return "Paper does not contain a valid PDF URL."
        return None

    @staticmethod
    def _skipped_item(paper: PaperCandidate, warning: str) -> PaperIngestionItem:
        return PaperIngestionItem(
            paper_id=paper.id,
            title=paper.title,
            status=IngestionStatus.SKIPPED,
            warnings=[warning],
        )

    @classmethod
    def _failed_item(
        cls,
        paper: PaperCandidate,
        stage: str,
        error: Exception,
        *,
        downloaded_file_path: str | None = None,
        content_hash: str | None = None,
        size_bytes: int | None = None,
    ) -> PaperIngestionItem:
        return PaperIngestionItem(
            paper_id=paper.id,
            title=paper.title,
            status=IngestionStatus.FAILED,
            downloaded_file_path=downloaded_file_path,
            content_hash=content_hash,
            size_bytes=size_bytes,
            error_stage=stage,
            error_type=type(error).__name__,
            error_message=cls._safe_error_message(error, downloaded_file_path),
        )

    @staticmethod
    def _parsed_item(
        paper: PaperCandidate,
        document: Document,
        downloaded_file_path: str,
        size_bytes: int,
        content_hash: str,
        warnings: list[str],
    ) -> PaperIngestionItem:
        return PaperIngestionItem(
            paper_id=paper.id,
            title=paper.title,
            status=IngestionStatus.PARSED,
            document=document,
            downloaded_file_path=downloaded_file_path,
            content_hash=content_hash,
            size_bytes=size_bytes,
            page_count=len(document.pages),
            warnings=warnings,
        )

    @staticmethod
    def _reuse_document(
        cached: Document, paper: PaperCandidate, downloaded_file_path: str
    ) -> Document:
        return cached.model_copy(
            update={
                "id": uuid4(),
                "paper_id": paper.id,
                "title": paper.title,
                "source_path": str(Path(downloaded_file_path)),
            },
            deep=True,
        )

    @classmethod
    def _safe_error_message(
        cls, error: Exception, downloaded_file_path: str | None
    ) -> str:
        message = str(error).replace("\r", " ").replace("\n", " ").strip()
        if downloaded_file_path:
            path = Path(downloaded_file_path)
            message = message.replace(downloaded_file_path, path.name)
            try:
                message = message.replace(str(path.resolve()), path.name)
            except OSError:
                pass
        message = cls._URL_RE.sub("[redacted-url]", message)
        message = cls._WINDOWS_PATH_RE.sub(lambda match: match.group(1), message)
        message = cls._POSIX_PATH_RE.sub(lambda match: match.group(1), message)
        return (message or type(error).__name__)[:500]

    @staticmethod
    def _stable_unique(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(values))
