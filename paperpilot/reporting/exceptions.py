"""Exception hierarchy for evidence-grounded report generation."""


class ReportingError(RuntimeError):
    """Base exception for deterministic reporting failures."""


class ReportGenerationError(ReportingError):
    """Base exception for composed report-generation service failures."""


class ReportContextBuildError(ReportGenerationError):
    """Raised when verified results cannot produce a report context."""


class ReportWritingError(ReportGenerationError):
    """Raised when the structured writer cannot produce a report."""


class ReportContextError(ReportingError):
    """Raised when a bounded report context cannot be constructed."""


class ReportWriterError(ReportingError):
    """Raised when structured report generation cannot be invoked."""


class ReportSchemaValidationError(ReportWriterError):
    """Raised when structured output does not satisfy the report schema."""


class ReportVerificationError(ReportGenerationError):
    """Raised when a report contains invalid evidence or citation references."""
