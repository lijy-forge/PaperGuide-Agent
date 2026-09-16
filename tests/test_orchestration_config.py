"""Unit tests for bounded orchestration retry and quality configuration."""

import unittest

from paperguide.orchestration import OrchestratorConfig
from pydantic import ValidationError


class TestOrchestratorConfig(unittest.TestCase):
    def test_defaults(self):
        config = OrchestratorConfig()

        self.assertEqual(config.max_retrieval_attempts, 2)
        self.assertEqual(config.max_ingestion_attempts_per_paper, 2)
        self.assertEqual(config.max_reader_attempts_per_paper, 2)
        self.assertEqual(config.max_verifier_attempts_per_paper, 2)
        self.assertEqual(config.minimum_verified_papers, 1)
        self.assertEqual(config.minimum_verification_score, 0.7)
        self.assertTrue(config.allow_degraded_completion)
        self.assertTrue(config.route_conflicts_to_human_review)

    def test_invalid_score_threshold_is_rejected(self):
        with self.assertRaises(ValidationError):
            OrchestratorConfig(minimum_verification_score=1.1)
        with self.assertRaises(ValidationError):
            OrchestratorConfig(minimum_verification_score=-0.1)

    def test_attempt_limits_must_be_at_least_one(self):
        fields = (
            "max_retrieval_attempts",
            "max_ingestion_attempts_per_paper",
            "max_reader_attempts_per_paper",
            "max_verifier_attempts_per_paper",
        )
        for field in fields:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                OrchestratorConfig(**{field: 0})

    def test_minimum_verified_papers_must_be_nonnegative(self):
        with self.assertRaises(ValidationError):
            OrchestratorConfig(minimum_verified_papers=-1)

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            OrchestratorConfig(retry_forever=True)


if __name__ == "__main__":
    unittest.main()
