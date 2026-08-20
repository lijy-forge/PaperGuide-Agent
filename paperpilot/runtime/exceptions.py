"""Typed errors for runtime configuration and command execution."""


class RuntimeErrorBase(RuntimeError):
    """Base exception for the PaperPilot runtime entry layer."""


class RuntimeConfigurationError(RuntimeErrorBase):
    """Raised when environment-backed runtime configuration is unsafe."""


class RuntimeHealthError(RuntimeErrorBase):
    """Raised when a runtime health check cannot be performed safely."""
