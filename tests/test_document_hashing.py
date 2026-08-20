"""Unit tests for deterministic streaming document hashing."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paperpilot.document import DocumentHashError, calculate_sha256


class TrackingReader:
    """Binary reader recording requested chunk sizes."""

    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0
        self.read_sizes: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class TestDocumentHashing(unittest.TestCase):
    def test_regular_file_sha256(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.pdf"
            payload = b"%PDF deterministic paper"
            path.write_bytes(payload)

            result = calculate_sha256(path)

        self.assertEqual(result, hashlib.sha256(payload).hexdigest())
        self.assertEqual(result, result.lower())

    def test_empty_file_sha256(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.pdf"
            path.touch()

            result = calculate_sha256(path)

        self.assertEqual(result, hashlib.sha256(b"").hexdigest())

    def test_missing_file_is_rejected(self):
        with self.assertRaises(DocumentHashError) as context:
            calculate_sha256("missing-paper.pdf")

        self.assertIn("does not exist", str(context.exception))

    def test_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DocumentHashError):
                calculate_sha256(directory)

    def test_file_is_read_in_chunks(self):
        payload = b"x" * (1024 * 1024 + 7)
        reader = TrackingReader(payload)
        with patch.object(Path, "exists", return_value=True), patch.object(
            Path, "is_file", return_value=True
        ), patch.object(Path, "open", return_value=reader):
            result = calculate_sha256("paper.pdf")

        self.assertEqual(result, hashlib.sha256(payload).hexdigest())
        self.assertGreaterEqual(len(reader.read_sizes), 3)
        self.assertTrue(all(size == 1024 * 1024 for size in reader.read_sizes))


if __name__ == "__main__":
    unittest.main()
