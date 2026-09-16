"""Task event query API tests."""

import unittest
from uuid import uuid4

from paperguide.application import ResearchTaskStatus
from paperguide.runtime.host import TaskEventType
from paperguide.progress.models import ProgressEventPayload, ProgressStage
from tests.api_fixtures import APITestRuntime


class APIEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = APITestRuntime(max_event_page_size=20)
        self.task = self.runtime.save_task(ResearchTaskStatus.RUNNING)
        for event_type, status in (
            (TaskEventType.TASK_CREATED, ResearchTaskStatus.CREATED),
            (TaskEventType.TASK_QUEUED, ResearchTaskStatus.QUEUED),
            (TaskEventType.TASK_STARTED, ResearchTaskStatus.RUNNING),
        ):
            self.runtime.broker.record_event(
                self.task.task_id,
                event_type,
                status,
                host_id=self.runtime.host_id,
            )

    def tearDown(self) -> None:
        self.runtime.close()

    def test_event_pagination_is_stable(self) -> None:
        response = self.runtime.client.get(
            f"/api/v1/tasks/{self.task.task_id}/events?limit=2&offset=1"
        )
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload), 2)
        self.assertLess(payload[0]["event_id"], payload[1]["event_id"])

    def test_task_with_no_events_returns_empty_list(self) -> None:
        task = self.runtime.save_task(ResearchTaskStatus.QUEUED)
        response = self.runtime.client.get(
            f"/api/v1/tasks/{task.task_id}/events"
        )
        self.assertEqual(response.json(), [])

    def test_page_size_over_limit_returns_422(self) -> None:
        response = self.runtime.client.get(
            f"/api/v1/tasks/{self.task.task_id}/events?limit=21"
        )
        self.assertEqual(response.status_code, 422)

    def test_event_type_filter_is_applied_before_pagination(self) -> None:
        response = self.runtime.client.get(
            f"/api/v1/tasks/{self.task.task_id}/events"
            "?event_type=task_started&limit=1"
        )
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["event_type"], "task_started")

    def test_event_response_omits_host_and_sensitive_metadata(self) -> None:
        response = self.runtime.client.get(
            f"/api/v1/tasks/{self.task.task_id}/events"
        )
        serialized = response.text
        self.assertNotIn(str(self.runtime.host_id), serialized)
        self.assertNotIn("question", serialized)
        self.assertNotIn("lease_owner", serialized)

    def test_missing_task_returns_404(self) -> None:
        response = self.runtime.client.get(f"/api/v1/tasks/{uuid4()}/events")
        self.assertEqual(response.status_code, 404)

    def test_public_progress_projection_and_incremental_cursor(self) -> None:
        self.runtime.broker.record_progress_event(
            self.task.task_id,
            TaskEventType.PDF_PROCESSING_PROGRESS,
            ResearchTaskStatus.RUNNING,
            ProgressEventPayload(
                stage=ProgressStage.PDF_PROCESSING,
                completed=1,
                total=2,
                succeeded=1,
                failed=0,
                skipped=0,
                paper_title_preview="A public paper title",
            ),
            dedupe_key="pdf:1:2",
        )
        page = self.runtime.client.get(f"/api/v1/tasks/{self.task.task_id}/events")
        event = page.json()[-1]
        self.assertEqual(event["progress"]["completed"], 1)
        self.assertNotIn("host_id", page.text)
        incremental = self.runtime.client.get(
            f"/api/v1/tasks/{self.task.task_id}/events?after_id={event['event_id']}"
        )
        self.assertEqual(incremental.json(), [])


if __name__ == "__main__":
    unittest.main()
