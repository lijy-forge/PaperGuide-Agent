"""A key written to .env must actually reach the runtime."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from paperguide.runtime.env_file import ENV_FILENAME, find_env_file, load_env_file

_VARIABLE = "PAPERGUIDE_TEST_ONLY_VALUE"


class EnvFileTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop(_VARIABLE, None)

    @staticmethod
    def _write(directory: Path, body: str) -> None:
        (directory / ENV_FILENAME).write_text(body, "utf-8")

    def test_a_value_in_the_file_reaches_the_environment(self) -> None:
        os.environ.pop(_VARIABLE, None)
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            self._write(directory, f"{_VARIABLE}=from-the-file\n")

            self.assertIsNotNone(load_env_file(directory))
            self.assertEqual(os.environ[_VARIABLE], "from-the-file")

    def test_the_existing_environment_wins(self) -> None:
        # An export on the command line is the more specific instruction, and
        # replacing it from a stale file would be silent and hard to explain.
        os.environ[_VARIABLE] = "from-the-shell"
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            self._write(directory, f"{_VARIABLE}=from-the-file\n")

            load_env_file(directory)
            self.assertEqual(os.environ[_VARIABLE], "from-the-shell")

    def test_a_missing_file_is_not_an_error(self) -> None:
        # The environment may come entirely from the shell or a container.
        with TemporaryDirectory() as raw:
            self.assertIsNone(load_env_file(Path(raw)))

    def test_the_nearest_file_above_the_directory_is_used(self) -> None:
        os.environ.pop(_VARIABLE, None)
        with TemporaryDirectory() as raw:
            root = Path(raw)
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            self._write(root, f"{_VARIABLE}=from-the-root\n")

            # resolve() on both sides: on macOS a temporary directory sits
            # under /var, which is a symlink to /private/var.
            self.assertEqual(
                find_env_file(nested), (root / ENV_FILENAME).resolve()
            )
            load_env_file(nested)
            self.assertEqual(os.environ[_VARIABLE], "from-the-root")
