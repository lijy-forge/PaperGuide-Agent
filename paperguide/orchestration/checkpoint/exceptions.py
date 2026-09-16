"""Exceptions raised by orchestration checkpoint stores."""


class CheckpointError(Exception):
    """Base exception for checkpoint storage failures."""


class CheckpointNotFoundError(CheckpointError):
    """Raised when a checkpoint does not exist for a requested run."""
