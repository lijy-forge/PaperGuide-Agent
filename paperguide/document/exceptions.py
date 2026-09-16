"""Document-layer exception hierarchy."""


class PdfDownloadError(RuntimeError):
    """Base exception for failures while downloading or storing a PDF."""


class PdfNetworkError(PdfDownloadError):
    """Raised for HTTP, timeout, or connection failures during download."""


class InvalidPDFError(PdfDownloadError):
    """Raised when downloaded content fails PDF validation."""


class PdfParseError(RuntimeError):
    """Raised when a local PDF cannot be opened or parsed."""
