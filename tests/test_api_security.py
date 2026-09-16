"""HTTP security headers, request IDs, CORS, and safe error tests."""

import copy
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from paperguide.api import APISettings
from paperguide.api.dependencies import create_default_dependencies
from paperguide.runtime import RuntimeSettings

from tests.api_fixtures import APITestRuntime


class APISecurityTests(unittest.TestCase):
    def test_api_settings_reject_secret_fields(self) -> None:
        with self.assertRaises(ValidationError):
            APISettings.model_validate(
                {
                    "artifact_root": "artifacts",
                    "api_key": "must-not-be-accepted",
                }
            )

    def test_request_id_is_returned_and_matches_error_envelope(self) -> None:
        runtime = APITestRuntime()
        try:
            response = runtime.client.get("/api/v1/tasks/not-a-uuid")
            request_id = response.headers["x-request-id"]
            UUID(request_id)
            self.assertEqual(response.json()["request_id"], request_id)
        finally:
            runtime.close()

    def test_security_headers_are_present(self) -> None:
        runtime = APITestRuntime()
        try:
            response = runtime.client.get("/health/live")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["x-frame-options"], "DENY")
            self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        finally:
            runtime.close()

    def test_internal_error_does_not_expose_secret_or_stack_trace(self) -> None:
        secret = "api_key=never-expose-this"
        runtime = APITestRuntime(raise_server_exceptions=False)

        @runtime.app.get("/test-internal-error")
        def fail_for_test():
            raise RuntimeError(secret)

        try:
            response = runtime.client.get("/test-internal-error")
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["code"], "INTERNAL_ERROR")
            self.assertNotIn(secret, response.text)
            self.assertNotIn("traceback", response.text.casefold())
        finally:
            runtime.close()

    def test_cors_is_disabled_by_default(self) -> None:
        runtime = APITestRuntime()
        try:
            response = runtime.client.options(
                "/api/v1/research",
                headers={
                    "Origin": "https://untrusted.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
            self.assertNotIn("access-control-allow-origin", response.headers)
            self.assertNotIn("access-control-allow-credentials", response.headers)
        finally:
            runtime.close()

    def test_configured_cors_never_enables_credentials(self) -> None:
        runtime = APITestRuntime(cors_origins=["https://dashboard.example"])
        try:
            response = runtime.client.options(
                "/api/v1/research",
                headers={
                    "Origin": "https://dashboard.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
            self.assertEqual(
                response.headers["access-control-allow-origin"],
                "https://dashboard.example",
            )
            self.assertNotEqual(
                response.headers.get("access-control-allow-credentials"),
                "true",
            )
        finally:
            runtime.close()

    def test_default_runtime_allows_only_local_dashboard_origins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dependencies = create_default_dependencies(
                runtime_settings=RuntimeSettings(
                    export_directory=Path(directory) / "artifacts"
                )
            )

        self.assertEqual(
            dependencies.settings.cors_allowed_origins,
            ["http://127.0.0.1:5173", "http://localhost:5173"],
        )

    def test_request_payload_is_not_modified(self) -> None:
        runtime = APITestRuntime()
        payload = {
            "question": "Immutable API payload",
            "max_papers": 5,
            "export_format": "markdown",
        }
        original = copy.deepcopy(payload)
        try:
            response = runtime.client.post("/api/v1/research", json=payload)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(payload, original)
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
