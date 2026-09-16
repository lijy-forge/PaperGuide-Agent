"""Unified safe file export service for evidence-grounded reports."""

import hashlib
import os
import re
import tempfile
import unicodedata
from pathlib import Path

from paperguide.reporting import ResearchReport, SurveyRenderFormat, SurveyRenderService, SurveyReport
from paperguide.runtime_context import (
    ExecutionAbortedError,
    ExecutionContext,
    get_execution_context,
)

from .exceptions import (
    ExportArtifactExistsError,
    ExportArtifactWriteError,
    ExportError,
    ExportPathTraversalError,
    ExportServiceError,
    InvalidExportFilenameError,
)
from .html import HTMLExporter
from .integrity import ArtifactFormatIntegrityValidator
from .markdown import MarkdownExporter
from .models import ArtifactMetadata, ExportFormat, ExportResult
from .pdf import PDFExporter
from .verifier import ExportVerifier

_EXTENSIONS = {
    ExportFormat.MARKDOWN: ".md",
    ExportFormat.HTML: ".html",
    ExportFormat.PDF: ".pdf",
}
_MEDIA_TYPES = {
    ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
    ExportFormat.HTML: "text/html; charset=utf-8",
    ExportFormat.PDF: "application/pdf",
}
_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class ExportService:
    """Select an exporter and atomically publish a checksummed artifact."""

    def __init__(
        self,
        output_directory: str | Path,
        *,
        verifier: ExportVerifier | None = None,
        markdown_exporter: MarkdownExporter | None = None,
        html_exporter: HTMLExporter | None = None,
        pdf_exporter: PDFExporter | None = None,
        survey_renderer: SurveyRenderService | None = None,
        integrity_validator: ArtifactFormatIntegrityValidator | None = None,
        overwrite: bool = False,
    ) -> None:
        self.verifier = verifier or ExportVerifier()
        self.markdown_exporter = markdown_exporter or MarkdownExporter(self.verifier)
        self.html_exporter = html_exporter or HTMLExporter(self.verifier)
        self.pdf_exporter = pdf_exporter or PDFExporter(verifier=self.verifier)
        self.survey_renderer = survey_renderer or SurveyRenderService()
        self.integrity_validator = integrity_validator or ArtifactFormatIntegrityValidator()
        self.overwrite = overwrite
        directory = Path(output_directory)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self.output_directory = directory.resolve(strict=True)
        except OSError as error:
            raise ExportServiceError(
                f"could not initialize export directory {directory}"
            ) from error
        if not self.output_directory.is_dir():
            raise ExportServiceError("configured export path is not a directory")

    def export(
        self,
        report: ResearchReport | SurveyReport,
        export_format: ExportFormat,
        *,
        filename: str | None = None,
        overwrite: bool | None = None,
    ) -> ExportResult:
        """Validate, render, atomically publish, and checksum one report."""

        try:
            resolved_format = ExportFormat(export_format)
        except (TypeError, ValueError) as error:
            message = f"unsupported export format: {export_format!r}"
            raise ExportServiceError(message) from error

        is_survey = isinstance(report, SurveyReport)
        safe_report = report.model_copy(deep=True) if is_survey else self.verifier.verify(report)
        execution_context = get_execution_context()
        if execution_context is not None:
            execution_context.cancellation_token.raise_if_cancelled()
        safe_filename = self._resolve_filename(
            (
                filename
                if filename is not None
                else (
                    "research-report"
                    if execution_context is not None
                    else self._generate_filename(safe_report.title)
                )
            ),
            resolved_format,
        )
        target_directory = (
            self._execution_directory(execution_context)
            if execution_context is not None
            else self.output_directory
        )
        target = self._resolve_target(safe_filename, target_directory)
        if execution_context is not None and target.exists():
            return self._existing_result(
                target,
                resolved_format,
                safe_report,
                execution_context,
            )
        allow_overwrite = self.overwrite if overwrite is None else overwrite
        if target.exists() and not allow_overwrite:
            raise ExportArtifactExistsError(
                f"export artifact already exists: {target.name}"
            )

        temporary_path: Path | None = None
        try:
            if is_survey:
                rendered = self.survey_renderer.render(
                    safe_report, SurveyRenderFormat(resolved_format.value)
                )
                payload = (
                    rendered.content
                    if isinstance(rendered.content, bytes)
                    else rendered.content.encode("utf-8")
                )
                media_type = rendered.mime_type
                if rendered.extension != _EXTENSIONS[resolved_format]:
                    raise ExportServiceError("ARTIFACT_FORMAT_MISMATCH")
                self.integrity_validator.validate(
                    resolved_format, safe_filename, media_type, payload
                )
                temporary_path = self._write_temporary(payload, target_directory)
            elif resolved_format is ExportFormat.MARKDOWN:
                rendered = self.markdown_exporter.export(safe_report)
                payload = self._text_payload(rendered)
                self.integrity_validator.validate(
                    resolved_format, safe_filename, rendered.media_type, payload
                )
                temporary_path = self._write_temporary(payload, target_directory)
            elif resolved_format is ExportFormat.HTML:
                rendered = self.html_exporter.export(safe_report)
                payload = self._text_payload(rendered)
                self.integrity_validator.validate(
                    resolved_format, safe_filename, rendered.media_type, payload
                )
                temporary_path = self._write_temporary(payload, target_directory)
            else:
                temporary_path = self._temporary_path(
                    ".pdf.tmp",
                    target_directory,
                )
                rendered = self.pdf_exporter.export(safe_report, temporary_path)
                payload = temporary_path.read_bytes()
                self.integrity_validator.validate(
                    resolved_format, safe_filename, rendered.media_type, payload
                )

            if execution_context is not None:
                execution_context.cancellation_token.raise_if_cancelled()
            if target.exists() and not allow_overwrite:
                raise ExportArtifactExistsError(
                    f"export artifact already exists: {target.name}"
                )
            if allow_overwrite:
                os.replace(temporary_path, target)
            else:
                try:
                    os.link(temporary_path, target)
                except FileExistsError as error:
                    raise ExportArtifactExistsError(
                        f"export artifact already exists: {target.name}"
                    ) from error
                temporary_path.unlink()
            temporary_path = None
        except (ExportError, ExecutionAbortedError):
            raise
        except OSError as error:
            raise ExportArtifactWriteError(
                f"could not atomically publish artifact {target.name}"
            ) from error
        except Exception as error:
            raise ExportServiceError("report export failed") from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

        digest = hashlib.sha256(payload).hexdigest()
        try:
            published_payload = target.read_bytes()
        except OSError as error:
            raise ExportArtifactWriteError(
                f"could not verify published artifact {target.name}"
            ) from error
        if hashlib.sha256(published_payload).hexdigest() != digest:
            raise ExportArtifactWriteError("published artifact checksum mismatch")
        self.integrity_validator.validate(
            resolved_format,
            target.name,
            _MEDIA_TYPES[resolved_format],
            published_payload,
        )

        artifact = ArtifactMetadata(
            format=resolved_format,
            file_path=str(target),
            size_bytes=len(published_payload),
            sha256=digest,
            execution_id=(
                execution_context.execution_id
                if execution_context is not None
                else None
            ),
            task_id=(
                execution_context.task_id
                if execution_context is not None
                else None
            ),
        )
        return ExportResult(
            format=resolved_format,
            media_type=_MEDIA_TYPES[resolved_format],
            content=(
                published_payload.decode("utf-8")
                if resolved_format is not ExportFormat.PDF
                else None
            ),
            file_path=str(target),
            size_bytes=len(published_payload),
            warnings=list(rendered.warnings),
            artifact=artifact,
        )

    @staticmethod
    def _text_payload(result: ExportResult) -> bytes:
        if result.content is None:
            raise ExportServiceError("text exporter returned no content")
        return result.content.encode("utf-8")

    def _resolve_filename(self, filename: str, export_format: ExportFormat) -> str:
        if not filename or filename in (".", ".."):
            raise InvalidExportFilenameError("export filename must not be empty")
        if Path(filename).is_absolute() or "/" in filename or "\\" in filename:
            raise ExportPathTraversalError("export filename must be a single basename")
        if _INVALID_FILENAME_RE.search(filename):
            raise InvalidExportFilenameError(
                "export filename contains invalid characters"
            )
        if filename[-1] in (" ", "."):
            raise InvalidExportFilenameError(
                "export filename cannot end with a space or period"
            )
        suffix = Path(filename).suffix.casefold()
        expected_suffix = _EXTENSIONS[export_format]
        if suffix and suffix != expected_suffix:
            raise InvalidExportFilenameError(
                f"filename extension must be {expected_suffix}"
            )
        if not suffix:
            filename = f"{filename}{expected_suffix}"
        stem = Path(filename).stem.casefold()
        if stem in _RESERVED_WINDOWS_NAMES:
            raise InvalidExportFilenameError("export filename is reserved")
        if len(filename) > 180:
            raise InvalidExportFilenameError("export filename is too long")
        return filename

    def _resolve_target(self, filename: str, directory: Path) -> Path:
        target = (directory / filename).resolve(strict=False)
        if target.parent != directory:
            raise ExportPathTraversalError("export target escapes output directory")
        return target

    def _execution_directory(self, context: ExecutionContext) -> Path:
        safe_execution_id = re.sub(
            r"[^A-Za-z0-9._-]",
            "_",
            context.execution_id,
        )
        directory = (
            self.output_directory / str(context.task_id) / safe_execution_id
        ).resolve(strict=False)
        try:
            directory.relative_to(self.output_directory)
            directory.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as error:
            raise ExportPathTraversalError(
                "artifact execution directory is invalid"
            ) from error
        return directory

    @staticmethod
    def _generate_filename(title: str) -> str:
        normalized = unicodedata.normalize("NFKD", title)
        ascii_title = normalized.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_title).strip("-").casefold()
        return (slug[:120].rstrip("-") or "research-report")

    def _temporary_path(self, suffix: str, directory: Path | None = None) -> Path:
        descriptor, name = tempfile.mkstemp(
            prefix=".paperguide-",
            suffix=suffix,
            dir=directory or self.output_directory,
        )
        os.close(descriptor)
        return Path(name)

    def _write_temporary(
        self,
        payload: bytes,
        directory: Path | None = None,
    ) -> Path:
        path = self._temporary_path(".tmp", directory)
        try:
            with path.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ExportArtifactWriteError(
                "could not write temporary artifact"
            ) from error
        return path

    def _existing_result(
        self,
        target: Path,
        export_format: ExportFormat,
        report: ResearchReport | SurveyReport,
        context: ExecutionContext,
    ) -> ExportResult:
        try:
            payload = target.read_bytes()
        except OSError as error:
            raise ExportArtifactWriteError(
                "could not read existing execution artifact"
            ) from error
        digest = hashlib.sha256(payload).hexdigest()
        self.integrity_validator.validate(
            export_format,
            target.name,
            _MEDIA_TYPES[export_format],
            payload,
        )
        artifact = ArtifactMetadata(
            format=export_format,
            file_path=str(target),
            size_bytes=len(payload),
            sha256=digest,
            execution_id=context.execution_id,
            task_id=context.task_id,
        )
        return ExportResult(
            format=export_format,
            media_type=_MEDIA_TYPES[export_format],
            content=(
                payload.decode("utf-8")
                if export_format is not ExportFormat.PDF
                else None
            ),
            file_path=str(target),
            size_bytes=len(payload),
            warnings=list(report.warnings),
            artifact=artifact,
        )
