"""Validated HTTP downloader for candidate-paper PDF files."""

import socket
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from paperpilot.domain import PaperCandidate
from paperpilot.services import MetadataNormalizer

from .exceptions import InvalidPDFError, PdfDownloadError, PdfNetworkError
from .models import DownloadedPDF


class PdfDownloader:
    """Download and validate a paper PDF without modifying its candidate."""

    DEFAULT_TIMEOUT_SECONDS = 15.0
    DEFAULT_MAX_SIZE_BYTES = 50 * 1024 * 1024
    DEFAULT_USER_AGENT = "PaperPilot"
    READ_CHUNK_SIZE = 64 * 1024
    ALLOWED_CONTENT_TYPES = frozenset(
        {"application/pdf", "application/octet-stream"}
    )

    def __init__(
        self,
        download_dir: str | Path,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Callable[..., Any] | None = None,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be greater than zero")
        if not user_agent.strip():
            raise ValueError("user_agent must not be empty")
        self.download_dir = Path(download_dir)
        self.timeout_seconds = timeout_seconds
        self.max_size_bytes = max_size_bytes
        self.user_agent = user_agent.strip()
        self._opener = opener or urlopen

    def download(self, paper: PaperCandidate) -> DownloadedPDF:
        """Download, validate, and atomically store a candidate's PDF."""

        pdf_url = MetadataNormalizer.normalize_url(paper.pdf_url)
        if pdf_url is None:
            raise InvalidPDFError("paper does not contain a valid PDF URL")

        request = Request(
            pdf_url,
            headers={
                "Accept": "application/pdf",
                "User-Agent": self.user_agent,
            },
            method="GET",
        )
        payload = self._fetch_pdf(request)
        return self._store_pdf(paper, payload)

    def _fetch_pdf(self, request: Request) -> bytes:
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status < 200 or status >= 300:
                    raise PdfNetworkError(
                        f"PDF server returned unexpected HTTP status {status}"
                    )
                self._validate_headers(response)
                payload = self._read_limited(response)
        except (PdfNetworkError, InvalidPDFError):
            raise
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            raise PdfNetworkError(f"Unable to download PDF: {error}") from error

        if not payload:
            raise InvalidPDFError("downloaded PDF is empty")
        if not payload.startswith(b"%PDF"):
            raise InvalidPDFError("downloaded content does not have a PDF magic header")
        return payload

    def _validate_headers(self, response: Any) -> None:
        headers = getattr(response, "headers", {})
        content_type = (headers.get("Content-Type") or "").split(";", 1)[0]
        content_type = content_type.strip().casefold()
        if content_type not in self.ALLOWED_CONTENT_TYPES:
            raise InvalidPDFError(
                f"unexpected PDF Content-Type: {content_type or 'missing'}"
            )

        content_length = headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except (TypeError, ValueError) as error:
                raise InvalidPDFError("invalid PDF Content-Length header") from error
            if declared_size < 0:
                raise InvalidPDFError("invalid negative PDF Content-Length")
            if declared_size > self.max_size_bytes:
                raise InvalidPDFError(
                    f"PDF exceeds maximum size of {self.max_size_bytes} bytes"
                )

    def _read_limited(self, response: Any) -> bytes:
        chunks: list[bytes] = []
        total_size = 0
        while True:
            chunk = response.read(self.READ_CHUNK_SIZE)
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise InvalidPDFError("PDF response body must contain bytes")
            total_size += len(chunk)
            if total_size > self.max_size_bytes:
                raise InvalidPDFError(
                    f"PDF exceeds maximum size of {self.max_size_bytes} bytes"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _store_pdf(self, paper: PaperCandidate, payload: bytes) -> DownloadedPDF:
        temporary_path: Path | None = None
        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".part",
                prefix=f"{paper.id}-",
                dir=self.download_dir,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(payload)
            final_path = self.download_dir / f"{paper.id}.pdf"
            temporary_path.replace(final_path)
        except OSError as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise PdfDownloadError(f"Unable to store downloaded PDF: {error}") from error

        return DownloadedPDF(
            file_path=str(final_path.resolve()),
            paper_id=paper.id,
            size_bytes=len(payload),
        )
