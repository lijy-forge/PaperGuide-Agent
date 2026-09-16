"""Typed failures raised while assembling the PaperGuide application."""


class BootstrapError(RuntimeError):
    """Raised when the application object graph cannot be constructed safely."""
