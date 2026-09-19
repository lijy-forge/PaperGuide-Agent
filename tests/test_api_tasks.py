"""Task status and cancellation API tests."""

import unittest
from uuid import uuid4

from paperguide.application import ResearchTaskStatus
from paperguide.export import ExportFormat

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


class APITaskListTests(unittest.TestCase):
    """Listing is the only way to reach a task whose id the client never saw."""

    def setUp(self) -> None:
        self.runtime = APITestRuntime()

    def tearDown(self) -> None:
        self.runtime.close()

    def test_lists_tasks_newest_first_with_a_total(self) -> None:
        for _ in range(3):
            self.runtime.save_task(ResearchTaskStatus.QUEUED)
        self.runtime.save_task(ResearchTaskStatus.FAILED, error="boom")

        payload = self.runtime.client.get("/api/v1/tasks?limit=2").json()

        self.assertEqual(payload["total"], 4)
        self.assertEqual(len(payload["items"]), 2)
        # The total counts every match, not the page, so a client can tell
        # "no more pages" from "no tasks at all".
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["offset"], 0)

    def test_filters_by_status(self) -> None:
        self.runtime.save_task(ResearchTaskStatus.QUEUED)
        failed = self.runtime.save_task(ResearchTaskStatus.FAILED, error="boom")

        payload = self.runtime.client.get("/api/v1/tasks?status=failed").json()

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["task_id"], str(failed.task_id))

    def test_paging_does_not_repeat_or_drop_a_task(self) -> None:
        for _ in range(5):
            self.runtime.save_task(ResearchTaskStatus.QUEUED)

        first = self.runtime.client.get("/api/v1/tasks?limit=2&offset=0").json()
        second = self.runtime.client.get("/api/v1/tasks?limit=2&offset=2").json()
        third = self.runtime.client.get("/api/v1/tasks?limit=2&offset=4").json()

        seen = [item["task_id"] for page in (first, second, third) for item in page["items"]]
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(set(seen)), 5)

    def test_rejects_out_of_range_paging(self) -> None:
        self.assertEqual(self.runtime.client.get("/api/v1/tasks?limit=0").status_code, 422)
        self.assertEqual(self.runtime.client.get("/api/v1/tasks?limit=101").status_code, 422)
        self.assertEqual(self.runtime.client.get("/api/v1/tasks?offset=-1").status_code, 422)
        self.assertEqual(
            self.runtime.client.get("/api/v1/tasks?status=bogus").status_code, 422
        )

    def test_listing_leaks_no_question_or_error_text(self) -> None:
        self.runtime.save_task(
            ResearchTaskStatus.FAILED, error="ValueError at /Users/someone/secret.py"
        )
        response = self.runtime.client.get("/api/v1/tasks")

        # The values must be named: with none passed the helper compares an
        # empty set of forbidden strings and passes whatever the response says.
        self.assertTrue(
            response_has_no_sensitive_text(
                response.json(),
                "Sensitive research question",
                "ValueError",
                "/Users/someone/secret.py",
            )
        )


class APIFailureCodeTests(unittest.TestCase):
    """A failure the caller can act on must be distinguishable from a crash."""

    def setUp(self) -> None:
        self.runtime = APITestRuntime()

    def tearDown(self) -> None:
        self.runtime.close()

    def _code_for(self, error: str) -> str | None:
        task = self.runtime.save_task(ResearchTaskStatus.FAILED, error=error)
        response = self.runtime.client.get(f"/api/v1/tasks/{task.task_id}")
        return response.json()["error_code"]

    def test_actionable_rejections_keep_their_own_code(self) -> None:
        self.assertEqual(
            self._code_for("NO_PAPERS_IN_TIME_RANGE"), "NO_PAPERS_IN_TIME_RANGE"
        )
        self.assertEqual(
            self._code_for("NO_EVIDENCE_FOR_QUESTION"), "NO_EVIDENCE_FOR_QUESTION"
        )
        self.assertEqual(
            self._code_for("REPORT_QUALITY_REJECTED"), "REPORT_QUALITY_REJECTED"
        )

    def test_an_internal_message_never_reaches_the_client(self) -> None:
        # Anything not on the public list collapses, so a stack-trace-shaped
        # error string cannot escape by being stored in the same field.
        self.assertEqual(
            self._code_for("ValueError at /Users/someone/secret.py"), "TASK_FAILED"
        )
