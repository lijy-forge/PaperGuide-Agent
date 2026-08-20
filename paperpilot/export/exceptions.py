"""Exceptions raised by safe report exporters."""


class ExportError(RuntimeError):
    """Base exception for report export failures."""


class ExportValidationError(ExportError):
    """Raised when a report is not safe or complete enough to export."""


class ExportWriteError(ExportError):
    """Raised when rendered export content cannot be written."""


class PDFExportError(ExportError):
    """Raised when local HTML-to-PDF rendering or PDF writing fails."""


class ExportServiceError(ExportError):
    """Raised when unified export orchestration cannot complete safely."""


class InvalidExportFilenameError(ExportServiceError):
    """Raised when an artifact filename is empty, reserved, or unsafe."""


class ExportPathTraversalError(InvalidExportFilenameError):
    """Raised when a filename attempts to escape the configured directory."""


class ExportArtifactExistsError(ExportServiceError):
    """Raised when overwrite is disabled and the artifact already exists."""


class ExportArtifactWriteError(ExportServiceError):
    """Raised when atomic artifact publication or checksum validation fails."""


class ArtifactFormatIntegrityError(ExportServiceError):
    """Raised when filename, MIME type, and rendered bytes disagree."""
