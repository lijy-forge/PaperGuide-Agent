"""Security and Host-context tests for the explicit provider preflight."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paperguide.api.exceptions import APIError
from paperguide.api.routes.internal import provider_preflight
from paperguide.api.schemas import HealthResponse
from paperguide.runtime import RuntimeSettings
from paperguide.runtime.host import (
    HostProviderPreflight,
    HostStatus,
    ProviderFailureCategory,
    ProviderPreflightResult,
    ProviderPreflightStatus,
    TaskHost,
)
from starlette.requests import Request

from tests.api_fixtures import APITestRuntime


class _ProviderError(RuntimeError):
    def __init__(self, status_code: int, message: str = "provider failure") -> None:
        super().__init__(message)
        self.status_code = status_code


class _FakeLLM:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return kwargs["response_model"](ok="ok") if self.result is None else self.result


class ProviderPreflightTests(unittest.TestCase):
    def probe(self, *, llm=None, environ=None):
        return HostProviderPreflight(
            llm or _FakeLLM(),
            provider="deepseek",
            model="deepseek-v4-flash",
            environ=environ,
        )

    def test_missing_credential_is_safe_and_does_not_invoke_provider(self) -> None:
        llm = _FakeLLM()
        result = self.probe(llm=llm, environ={}).run()
        self.assertEqual(result.status, ProviderPreflightStatus.FAIL)
        self.assertFalse(result.credential_present)
        self.assertEqual(result.failure_category, ProviderFailureCategory.PROVIDER_AUTH)
        self.assertEqual(result.safe_exception_class, "CredentialMissing")
        self.assertEqual(llm.calls, 0)

    def test_success_reuses_structured_provider_boundary(self) -> None:
        llm = _FakeLLM()
        result = self.probe(
            llm=llm,
            environ={"DEEPSEEK_API_KEY": "test-secret"},
        ).run()
        self.assertEqual(result.status, ProviderPreflightStatus.PASS)
        self.assertEqual(result.failure_category, ProviderFailureCategory.NONE)
        self.assertEqual(llm.calls, 1)
        self.assertNotIn("test-secret", result.model_dump_json())

    def test_http_statuses_have_safe_categories(self) -> None:
        cases = {
            401: ProviderFailureCategory.PROVIDER_AUTH,
            403: ProviderFailureCategory.PROVIDER_AUTH,
            402: ProviderFailureCategory.PROVIDER_BILLING,
            429: ProviderFailureCategory.PROVIDER_RATE_LIMIT,
            503: ProviderFailureCategory.PROVIDER_SERVER_ERROR,
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                result = self.probe(
                    llm=_FakeLLM(error=_ProviderError(status, "token=leak-me")),
                    environ={"DEEPSEEK_API_KEY": "test-secret"},
                ).run()
                self.assertEqual(result.status, ProviderPreflightStatus.FAIL)
                self.assertEqual(result.failure_category, expected)
                self.assertNotIn("leak-me", result.model_dump_json())
                self.assertNotIn("test-secret", result.model_dump_json())

    def test_connection_and_timeout_are_safe(self) -> None:
        for error, expected in (
            (TimeoutError("secret timeout"), ProviderFailureCategory.PROVIDER_TIMEOUT),
            (ConnectionError("secret connection"), ProviderFailureCategory.PROVIDER_CONNECTION),
        ):
            with self.subTest(error=type(error).__name__):
                result = self.probe(
                    llm=_FakeLLM(error=error),
                    environ={"DEEPSEEK_API_KEY": "test-secret"},
                ).run()
                self.assertEqual(result.failure_category, expected)
                self.assertNotIn("secret", result.model_dump_json())

    def test_host_executes_queued_preflight_using_its_container_llm(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "host-only-secret"},
            clear=False,
        ):
            llm = _FakeLLM()
            def factory(*_args, **kwargs):
                return SimpleNamespace(
                    application_service=SimpleNamespace(task_store=kwargs["task_store"]),
                    structured_llm=llm,
                )
            settings = RuntimeSettings(
                llm_provider="deepseek",
                model_name="deepseek-v4-flash",
                export_directory=Path(directory) / "artifacts",
            )
            host = TaskHost(
                settings,
                application_factory=factory,
            )
            host.broker.acquire_host(host.host_id)
            host.broker.heartbeat(host.host_id, status=HostStatus.RUNNING)
            request_id = host.broker.enqueue_provider_preflight()
            host._process_provider_preflight()
            result = host.broker.get_provider_preflight(request_id)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, ProviderPreflightStatus.PASS)
        self.assertEqual(llm.calls, 1)

    def test_preflight_does_not_create_or_change_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "host-only-secret"},
            clear=False,
        ):
            llm = _FakeLLM()
            def factory(*_args, **kwargs):
                return SimpleNamespace(
                    application_service=SimpleNamespace(task_store=kwargs["task_store"]),
                    structured_llm=llm,
                )
            settings = RuntimeSettings(
                llm_provider="deepseek",
                model_name="deepseek-v4-flash",
                export_directory=Path(directory) / "artifacts",
            )
            host = TaskHost(settings, application_factory=factory)
            host.broker.acquire_host(host.host_id)
            host.broker.heartbeat(host.host_id, status=HostStatus.RUNNING)
            request_id = host.broker.enqueue_provider_preflight()
            host._process_provider_preflight()
            tasks = host.task_store.list()
            result = host.broker.get_provider_preflight(request_id)

        self.assertEqual(tasks, [])
        self.assertIsNotNone(result)


class ProviderPreflightAPITests(unittest.TestCase):
    def safe_result(self) -> ProviderPreflightResult:
        return ProviderPreflightResult(
            status=ProviderPreflightStatus.PASS,
            credential_present=True,
            provider="deepseek",
            model="deepseek-v4-flash",
            elapsed_ms=1.0,
            failure_category=ProviderFailureCategory.NONE,
        )

    def test_internal_route_returns_only_safe_projection(self) -> None:
        runtime = APITestRuntime()
        try:
            runtime.broker.wait_provider_preflight = lambda *_a, **_k: self.safe_result()
            response = runtime.client.post("/internal/provider/preflight")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "pass")
            self.assertNotIn("request_id", response.json())
            self.assertNotIn("secret", response.text.casefold())
        finally:
            runtime.close()

    def test_preflight_is_loopback_only(self) -> None:
        runtime = APITestRuntime()
        try:
            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/internal/provider/preflight",
                    "headers": [],
                    "client": ("10.0.0.8", 12345),
                }
            )
            with self.assertRaises(APIError) as raised:
                provider_preflight(
                    request,
                    runtime.app.state.paperguide_dependencies,
                )
            self.assertEqual(raised.exception.status_code, 404)
            self.assertNotIn("/api/v1/internal", str(runtime.app.openapi()))
        finally:
            runtime.close()

    def test_readiness_does_not_enqueue_or_call_preflight(self) -> None:
        runtime = APITestRuntime()
        try:
            original_enqueue = runtime.broker.enqueue_provider_preflight
            calls = 0

            def tracked_enqueue():
                nonlocal calls
                calls += 1
                return original_enqueue()

            runtime.broker.enqueue_provider_preflight = tracked_enqueue
            response = runtime.client.get("/health/ready")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(HealthResponse.model_validate(response.json()).ready)
            self.assertEqual(calls, 0)
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
