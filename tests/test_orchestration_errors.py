"""Unit tests for sanitized orchestration errors and per-paper stage records."""

import unittest
from uuid import uuid4

from pydantic import ValidationError

from paperpilot.orchestration import (
    PaperStageRecord,
    PaperStageStatus,
    ResearchError,
    ResearchStep,
    sanitize_message,
)


def make_error(*, paper_id=None) -> ResearchError:
    return ResearchError(
        stage=ResearchStep.READING,
        paper_id=paper_id,
        error_type="ReaderError",
        message="Reader failed safely",
        recoverable=True,
        attempt=1,
    )


class TestResearchError(unittest.TestCase):
    def test_error_can_be_created(self):
        error = make_error()

        self.assertEqual(error.stage, ResearchStep.READING)
        self.assertEqual(error.attempt, 1)
        self.assertIsNotNone(error.id)
        self.assertIsNotNone(error.timestamp.tzinfo)

    def test_message_secrets_and_newlines_are_sanitized(self):
        error = ResearchError(
            stage=ResearchStep.RETRIEVAL,
            error_type="NetworkError",
            message=(
                "Authorization: Bearer secret-value\n"
                "api_key=sk-private token=second-secret"
            ),
            recoverable=True,
            attempt=0,
        )

        folded = error.message.casefold()
        self.assertNotIn("secret-value", folded)
        self.assertNotIn("sk-private", folded)
        self.assertNotIn("second-secret", folded)
        self.assertNotIn("authorization", folded)
        self.assertNotIn("api_key", folded)
        self.assertNotIn("bearer", folded)
        self.assertNotIn("token", folded)
        self.assertNotIn("\n", error.message)

    def test_message_is_limited_to_500_characters(self):
        result = sanitize_message("x" * 800)

        self.assertEqual(len(result), 500)

    def test_complete_authorization_header_is_removed(self):
        result = sanitize_message(
            "Request failed\nAuthorization: Basic highly-sensitive-value\nTimeout"
        )

        self.assertNotIn("highly-sensitive-value", result)
        self.assertNotIn("Authorization", result)
        self.assertIn("Timeout", result)

    def test_negative_attempt_is_rejected(self):
        with self.assertRaises(ValidationError):
            ResearchError(
                stage=ResearchStep.READING,
                error_type="ReaderError",
                message="Failure",
                recoverable=False,
                attempt=-1,
            )

    def test_error_json_round_trip(self):
        error = make_error(paper_id=uuid4())

        restored = ResearchError.model_validate_json(error.model_dump_json())

        self.assertEqual(restored, error)

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            ResearchError(
                stage=ResearchStep.READING,
                error_type="ReaderError",
                message="Failure",
                recoverable=False,
                attempt=0,
                secret="value",
            )


class TestPaperStageRecord(unittest.TestCase):
    def test_stage_status_can_transition(self):
        paper_id = uuid4()
        pending = PaperStageRecord(
            paper_id=paper_id,
            status=PaperStageStatus.PENDING,
            attempt=0,
        )
        verified = PaperStageRecord(
            paper_id=paper_id,
            status=PaperStageStatus.VERIFIED,
            attempt=1,
        )

        self.assertEqual(pending.status, PaperStageStatus.PENDING)
        self.assertEqual(verified.status, PaperStageStatus.VERIFIED)

    def test_stage_record_json_round_trip(self):
        paper_id = uuid4()
        record = PaperStageRecord(
            paper_id=paper_id,
            status=PaperStageStatus.FAILED,
            attempt=2,
            last_error=make_error(paper_id=paper_id),
        )

        restored = PaperStageRecord.model_validate_json(record.model_dump_json())

        self.assertEqual(restored, record)

    def test_stage_record_requires_paper_id(self):
        with self.assertRaises(ValidationError):
            PaperStageRecord(status=PaperStageStatus.PENDING)

    def test_last_error_must_reference_same_paper(self):
        with self.assertRaises(ValidationError):
            PaperStageRecord(
                paper_id=uuid4(),
                status=PaperStageStatus.FAILED,
                last_error=make_error(paper_id=uuid4()),
            )


if __name__ == "__main__":
    unittest.main()
