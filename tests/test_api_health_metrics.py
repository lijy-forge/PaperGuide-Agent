"""Liveness, readiness, and metrics API tests."""

import unittest
from dataclasses import replace

from paperguide.api import APIRuntimeHealthChecker
from tests.api_fixtures import APITestRuntime, FailingMetricsExporter


class APIHealthMetricsTests(unittest.TestCase):
    def test_liveness_is_independent_of_task_host(self) -> None:
        runtime = APITestRuntime()
        try:
            runtime.release_host()
            response = runtime.client.get("/health/live")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ready"])
            self.assertEqual(response.json()["kind"], "liveness")
        finally:
            runtime.close()

    def test_readiness_returns_200_when_runtime_is_ready(self) -> None:
        runtime = APITestRuntime(ready=True)
        try:
            dependencies = runtime.app.state.paperguide_dependencies
            runtime.app.state.paperguide_dependencies = replace(
                dependencies,
                runtime_health_checker=APIRuntimeHealthChecker(
                    runtime.broker,
                    runtime.artifact_root,
                ),
            )
            response = runtime.client.get("/health/ready")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ready"])
            self.assertNotIn(str(runtime.database_path), response.text)
        finally:
            runtime.close()

    def test_readiness_returns_503_when_runtime_is_unavailable(self) -> None:
        runtime = APITestRuntime(ready=False)
        try:
            runtime.release_host()
            dependencies = runtime.app.state.paperguide_dependencies
            runtime.app.state.paperguide_dependencies = replace(
                dependencies,
                runtime_health_checker=APIRuntimeHealthChecker(
                    runtime.broker,
                    runtime.artifact_root,
                ),
            )
            response = runtime.client.get("/health/ready")
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json()["ready"])
        finally:
            runtime.close()

    def test_metrics_returns_public_json_snapshot(self) -> None:
        runtime = APITestRuntime()
        try:
            submitted = runtime.client.post(
                "/api/v1/research",
                json={"question": "Metrics task"},
            )
            response = runtime.client.get("/api/v1/metrics")
            self.assertEqual(submitted.status_code, 202)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["submitted_total"], 1)
            self.assertNotIn("database", response.text.casefold())
            self.assertNotIn("pid", response.text.casefold())
        finally:
            runtime.close()

    def test_metrics_failure_returns_safe_503(self) -> None:
        runtime = APITestRuntime(metrics_exporter=FailingMetricsExporter())
        try:
            response = runtime.client.get("/api/v1/metrics")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["code"], "RUNTIME_NOT_READY")
            self.assertNotIn("C:/private", response.text)
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
