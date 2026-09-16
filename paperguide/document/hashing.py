"""Streaming content hashing for downloaded paper files."""

import hashlib
from pathlib import Path


class DocumentHashError(ValueError):
    """Raised when a document path cannot be hashed as a regular file."""


def calculate_sha256(file_path: str | Path) -> str:
    """Return the lowercase SHA-256 digest of a regular file."""

    path = Path(file_path)
    if not path.exists():
        raise DocumentHashError(f"document file does not exist: {path.name}")
    if not path.is_file():
        raise DocumentHashError(f"document path is not a regular file: {path.name}")

    digest = hashlib.sha256()
    try:
        with path.open("rb") as document_file:
            while chunk := document_file.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise DocumentHashError(f"unable to read document file: {path.name}") from error
    return digest.hexdigest()
