"""Exceptions raised while deriving recovery decisions."""


class RecoveryError(Exception):
    """Base exception for deterministic recovery failures."""


class RecoveryStateInvalidError(RecoveryError):
    """Raised when checkpoint state cannot safely be used for recovery."""
