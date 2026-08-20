"""FastAPI factory and OpenAPI tests."""

import importlib
import os
import subprocess
import sys
import tempfile
import threading
import unittest

from fastapi import FastAPI

from paperpilot.api import create_api_app
from tests.api_fixtures import APITestRuntime


class APIAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = APITestRuntime()

    def tearDown(self) -> None:
        self.runtime.close()

    def test_create_api_app_returns_fastapi(self) -> None:
        self.assertIsInstance(self.runtime.app, FastAPI)

    def test_openapi_schema_generates_with_expected_tags_and_paths(self) -> None:
        schema = self.runtime.app.openapi()
        self.assertEqual(schema["info"]["title"], "PaperPilot API")
        self.assertIn("/api/v1/research", schema["paths"])
        self.assertIn("/api/v1/tasks/{task_id}/artifact", schema["paths"])
        self.assertIn("/health/ready", schema["paths"])

    def test_import_has_no_host_graph_or_thread_side_effect(self) -> None:
        before = {thread.ident for thread in threading.enumerate()}
        module = importlib.import_module("paperpilot.api.app")
        after = {thread.ident for thread in threading.enumerate()}
        self.assertEqual(before, after)
        self.assertFalse(hasattr(module, "app"))
        self.assertTrue(callable(create_api_app))

    def test_clean_process_import_creates_no_runtime_files(self) -> None:
        repository = os.getcwd()
        environment = dict(os.environ)
        environment["PYTHONPATH"] = repository
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-c", "import paperpilot.api"],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            created = list(os.scandir(directory))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(created, [])


if __name__ == "__main__":
    unittest.main()
