"""Task status and cancellation API tests."""

import unittest
from uuid import uuid4

from paperpilot.application import ResearchTaskStatus
from paperpilot.export import ExportFormat
from tests.api_fixtures import APITestRuntime, response_has_no_sensitive_text


class APITaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = APITestRuntime()

    def tearDown(self) -> None:
        self.runtime.close()

    def test_query_queued_running_and_completed(self) -> None:
        queued = self.runtime.save_task(ResearchTaskStatus.QUEUED)
        running = self.runtime.save_task(ResearchTaskStatus.RUNNING)
        completed = self.runtime.completed_task(ExportFormat.MARKDOWN)
        responses = [
            self.runtime.client.get(f"/api/v1/tasks/{task.task_id}")
            for task in (queued, running, completed)
        ]
        self.assertEqual(
            [response.json()["status"] for response in responses],
            ["queued", "running", "completed"],
        )
        self.assertTrue(responses[-1].json()["artifact_available"])

    def test_missing_task_returns_404(self) -> None:
        response = self.runtime.client.get(f"/api/v1/tasks/{uuid4()}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "TASK_NOT_FOUND")

    def test_invalid_uuid_returns_422(self) -> None:
        response = self.runtime.client.get("/api/v1/tasks/not-a-uuid")
        self.assertEqual(response.status_code, 422)

    def test_cancel_queued_task(self) -> None:
        task = self.runtime.save_task(ResearchTaskStatus.QUEUED)
        response = self.runtime.client.post(
            f"/api/v1/tasks/{task.task_id}/cancel"
        )
        self.assertEqual(response.json()["status"], "cancelled")

    def test_cancel_running_requests_cooperative_cancellation(self) -> None:
        task = self.runtime.save_task(ResearchTaskStatus.RUNNING)
        response = self.runtime.client.post(
            f"/api/v1/tasks/{task.task_id}/cancel"
        )
        self.assertEqual(response.json()["status"], "cancel_requested")

    def test_cancel_terminal_task_is_idempotent(self) -> None:
        task = self.runtime.completed_task(ExportFormat.HTML)
        first = self.runtime.client.post(f"/api/v1/tasks/{task.task_id}/cancel")
        second = self.runtime.client.post(f"/api/v1/tasks/{task.task_id}/cancel")
        self.assertEqual(first.json()["status"], "completed")
        self.assertEqual(second.json(), first.json())

    def test_dead_letter_maps_without_raw_error(self) -> None:
        secret = "api_key=hidden-task-error"
        task = self.runtime.save_task(
            ResearchTaskStatus.DEAD_LETTER,
            error=f"retry failed ({secret})",
        )
        response = self.runtime.client.get(f"/api/v1/tasks/{task.task_id}")
        payload = response.json()
        self.assertEqual(payload["status"], "dead_letter")
        self.assertEqual(payload["error_code"], "TASK_DEAD_LETTER")
        self.assertTrue(response_has_no_sensitive_text(payload, secret, "question"))

    def test_runtime_unavailable_returns_503(self) -> None:
        task = self.runtime.save_task(ResearchTaskStatus.QUEUED)
        self.runtime.release_host()
        response = self.runtime.client.get(f"/api/v1/tasks/{task.task_id}")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
