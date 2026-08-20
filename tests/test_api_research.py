"""Research submission API tests."""

import copy
import unittest

from tests.api_fixtures import APITestRuntime


class APIResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = APITestRuntime(max_question_length=40)

    def tearDown(self) -> None:
        self.runtime.close()

    def test_submit_returns_202_without_waiting(self) -> None:
        response = self.runtime.client.post(
            "/api/v1/research",
            json={"question": "Compare visual SLAM methods"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "queued")
        self.assertIn("task_id", response.json())

    def test_request_maps_to_existing_research_request(self) -> None:
        response = self.runtime.client.post(
            "/api/v1/research",
            json={
                "question": "Map this request",
                "max_papers": 7,
                "export_format": "html",
            },
        )
        task_id = response.json()["task_id"]
        queued = self.runtime.broker.claim_next(self.runtime.host_id)
        self.assertEqual(str(queued.task_id), task_id)
        self.assertEqual(queued.request.max_papers, 7)
        self.assertEqual(queued.request.export_format.value, "html")

    def test_chinese_question_survives_api_and_broker_boundaries(self) -> None:
        question = "目标检测与视觉 SLAM 融合研究进展"
        response = self.runtime.client.post(
            "/api/v1/research",
            json={"question": question, "max_papers": 3, "export_format": "pdf"},
        )
        self.assertEqual(response.status_code, 202)
        queued = self.runtime.broker.claim_next(self.runtime.host_id)
        self.assertEqual(queued.request.question, question)

    def test_host_unavailable_returns_503(self) -> None:
        self.runtime.release_host()
        response = self.runtime.client.post(
            "/api/v1/research",
            json={"question": "Unavailable host"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "TASK_HOST_UNAVAILABLE")

    def test_invalid_question_and_max_papers_return_422(self) -> None:
        empty = self.runtime.client.post(
            "/api/v1/research",
            json={"question": "   "},
        )
        invalid_count = self.runtime.client.post(
            "/api/v1/research",
            json={"question": "Valid", "max_papers": 51},
        )
        too_long = self.runtime.client.post(
            "/api/v1/research",
            json={"question": "x" * 41},
        )
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(invalid_count.status_code, 422)
        self.assertEqual(too_long.status_code, 422)

    def test_unknown_fields_are_rejected_and_input_is_not_modified(self) -> None:
        payload = {"question": "Immutable", "unknown": "value"}
        original = copy.deepcopy(payload)
        response = self.runtime.client.post("/api/v1/research", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload, original)

    def test_question_is_not_written_to_access_log(self) -> None:
        question = "private-question-never-log"
        with self.assertLogs("paperpilot.api", level="INFO") as logs:
            response = self.runtime.client.post(
                "/api/v1/research",
                json={"question": question},
            )
        self.assertEqual(response.status_code, 202)
        self.assertNotIn(question, " ".join(logs.output))


if __name__ == "__main__":
    unittest.main()
