"""Models describing deterministic document-ingestion outcomes."""

from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import Document

NonNegativeInt = Annotated[int, Field(ge=0)]


class IngestionStatus(str, Enum):
    """Lifecycle status of one paper in a document-ingestion batch."""

    PENDING = "pending"
    SKIPPED = "skipped"
    DOWNLOADED = "downloaded"
    PARSED = "parsed"
    FAILED = "failed"


class PaperIngestionItem(BaseModel):
    """Outcome and diagnostics for one requested paper."""

    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    title: str
    status: IngestionStatus
    document: Document | None = None
    downloaded_file_path: str | None = None
    content_hash: str | None = None
    size_bytes: int | None = Field(default=None, gt=0)
    page_count: int | None = Field(default=None, ge=0)
    error_stage: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be empty")
        return value

    @model_validator(mode="after")
    def validate_status_details(self) -> "PaperIngestionItem":
        if self.error_stage is not None and self.status is not IngestionStatus.FAILED:
            raise ValueError("error_stage may only be set for failed ingestion")
        if self.status is IngestionStatus.PARSED:
            if self.document is None:
                raise ValueError("parsed ingestion must contain a document")
            if self.document.paper_id != self.paper_id:
                raise ValueError("document paper_id must match the ingestion item")
            if self.page_count is not None and self.page_count != len(self.document.pages):
                raise ValueError("page_count must match the parsed document")
        elif self.document is not None:
            raise ValueError("only parsed ingestion may contain a document")
        if self.status is IngestionStatus.FAILED and not self.error_message:
            raise ValueError("failed ingestion must contain an error_message")
        if (
            self.status is IngestionStatus.SKIPPED
            and not self.warnings
            and not self.error_message
        ):
            raise ValueError("skipped ingestion must explain why it was skipped")
        return self


class DocumentIngestionResult(BaseModel):
    """Completed batch result with documents, item outcomes, and statistics."""

    model_config = ConfigDict(extra="forbid")

    items: list[PaperIngestionItem]
    documents: list[Document]
    total_requested: NonNegativeInt
    total_eligible: NonNegativeInt
    total_downloaded: NonNegativeInt
    total_parsed: NonNegativeInt
    total_skipped: NonNegativeInt
    total_failed: NonNegativeInt
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_statistics(self) -> "DocumentIngestionResult":
        parsed_items = [
            item for item in self.items if item.status is IngestionStatus.PARSED
        ]
        skipped_count = sum(
            item.status is IngestionStatus.SKIPPED for item in self.items
        )
        failed_count = sum(
            item.status is IngestionStatus.FAILED for item in self.items
        )
        unfinished = [
            item
            for item in self.items
            if item.status in {IngestionStatus.PENDING, IngestionStatus.DOWNLOADED}
        ]
        downloaded_count = sum(
            item.downloaded_file_path is not None for item in self.items
        )

        if unfinished:
            raise ValueError("completed results cannot contain unfinished items")
        if self.total_requested != len(self.items):
            raise ValueError("total_requested must equal the number of items")
        if self.total_eligible != len(parsed_items) + failed_count:
            raise ValueError("total_eligible must equal parsed plus failed items")
        if self.total_downloaded != downloaded_count:
            raise ValueError("total_downloaded must match downloaded item records")
        if self.total_parsed != len(parsed_items):
            raise ValueError("total_parsed must match parsed items")
        if self.total_skipped != skipped_count:
            raise ValueError("total_skipped must match skipped items")
        if self.total_failed != failed_count:
            raise ValueError("total_failed must match failed items")
        if self.total_parsed != len(self.documents):
            raise ValueError("documents must contain every parsed result exactly once")
        expected_documents = [item.document for item in parsed_items]
        if self.documents != expected_documents:
            raise ValueError("documents must follow parsed-item order")
        return self
