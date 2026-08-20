"""Public document-layer interface for PaperPilot AI."""

from .cleaning import DocumentCleaningConfig, DocumentTextCleaner
from .downloader import PdfDownloader
from .exceptions import (
    InvalidPDFError,
    PdfDownloadError,
    PdfNetworkError,
    PdfParseError,
)
from .hashing import DocumentHashError, calculate_sha256
from .ingestion import DocumentIngestionPipeline
from .ingestion_models import (
    DocumentIngestionResult,
    IngestionStatus,
    PaperIngestionItem,
)
from .models import Document, DownloadedPDF, Page, Section
from .parser import PdfParser

__all__ = [
    "Document",
    "DocumentCleaningConfig",
    "DocumentHashError",
    "DocumentIngestionPipeline",
    "DocumentIngestionResult",
    "DocumentTextCleaner",
    "DownloadedPDF",
    "IngestionStatus",
    "InvalidPDFError",
    "Page",
    "PaperIngestionItem",
    "PdfDownloadError",
    "PdfDownloader",
    "PdfNetworkError",
    "PdfParseError",
    "PdfParser",
    "Section",
    "calculate_sha256",
]
