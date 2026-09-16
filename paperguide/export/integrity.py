"""Deterministic filename, MIME, and content checks for export artifacts."""

from __future__ import annotations

from pathlib import Path

from .exceptions import ArtifactFormatIntegrityError
from .models import ExportFormat


class ArtifactFormatIntegrityValidator:
    """Require one coherent format identity before an artifact is published."""

    _EXTENSIONS = {
        ExportFormat.MARKDOWN: ".md",
        ExportFormat.HTML: ".html",
        ExportFormat.PDF: ".pdf",
    }
    _MIME_TYPES = {
        ExportFormat.MARKDOWN: "text/markdown",
        ExportFormat.HTML: "text/html",
        ExportFormat.PDF: "application/pdf",
    }

    def validate(
        self,
        export_format: ExportFormat,
        filename: str,
        media_type: str,
        payload: bytes,
    ) -> None:
        """Reject extension/MIME/magic mismatches with one stable code."""

        resolved = ExportFormat(export_format)
        suffix = Path(filename).suffix.casefold()
        mime = media_type.split(";", 1)[0].strip().casefold()
        if suffix != self._EXTENSIONS[resolved] or mime != self._MIME_TYPES[resolved]:
            raise ArtifactFormatIntegrityError("ARTIFACT_FORMAT_MISMATCH")
        stripped = payload.lstrip()
        lower = stripped[:128].lower()
        if resolved is ExportFormat.PDF:
            valid = payload.startswith(b"%PDF-")
        elif resolved is ExportFormat.HTML:
            valid = lower.startswith(b"<!doctype html") or lower.startswith(b"<html")
        else:
            valid = not payload.startswith(b"%PDF-") and not (
                lower.startswith(b"<!doctype html") or lower.startswith(b"<html")
            )
        if not valid:
            raise ArtifactFormatIntegrityError("ARTIFACT_FORMAT_MISMATCH")
