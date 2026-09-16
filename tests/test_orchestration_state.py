"""Unit tests for the LangGraph-ready ResearchState contract."""

import json
import unittest
from uuid import UUID

from paperguide.analysis import PaperAnalysisResult
from paperguide.domain import (
    Author,
    FullTextStatus,
    PaperCandidate,
    PaperSource,
    ResearchConfig,
)
from paperguide.orchestration import (
    NextAction,
    ResearchStep,
    StateValidationError,
    create_initial_state,
    state_from_json,
    state_to_json,
    validate_state,
)

from .verification_fixtures import make_analysis


def make_config(question: str = "Analyze visual SLAM") -> ResearchConfig:
    return ResearchConfig(
        question=question,
        start_year=2024,
        end_year=2026,
        max_papers=10,
        sources=[PaperSource.ARXIV],
    )


def make_paper() -> PaperCandidate:
    return PaperCandidate(
        title="A Paper",
        normalized_title="a paper",
        abstract=None,
        authors=[Author(full_name="Ada Researcher", affiliations=[])],
        publication_year=2025,
        venue=None,
        doi=None,
        arxiv_id=None,
        semantic_scholar_id=None,
        openalex_id=None,
        sources=[PaperSource.ARXIV],
        landing_page_url=None,
        pdf_url="https://arxiv.org/pdf/2501.00001.pdf",
        citation_count=None,
        full_text_status=FullTextStatus.AVAILABLE,
        relevance_score=None,
        selection_reason=None,
    )


class TestResearchState(unittest.TestCase):
    def test_create_initial_state(self):
        config = make_config()

        state = create_initial_state(config.question, config)

        self.assertEqual(state["question"], config.question)
        self.assertEqual(state["research_config"], config)
        self.assertEqual(state["current_step"], ResearchStep.INITIALIZED)
        self.assertEqual(state["next_action"], NextAction.RETRIEVE)
        self.assertIsInstance(state["run_id"], UUID)

    def test_collection_fields_are_initialized_independently(self):
        first = create_initial_state("Question", make_config("Question"))
        second = create_initial_state("Question", make_config("Question"))

        self.assertEqual(first["papers"], [])
        self.assertEqual(first["documents"], {})
        self.assertEqual(first["analyses"], {})
        self.assertEqual(first["verification_results"], {})
        self.assertEqual(first["verified_results"], {})
        self.assertEqual(first["errors"], [])
        self.assertEqual(first["warnings"], [])
        self.assertIsNot(first["papers"], second["papers"])
        self.assertNotEqual(first["run_id"], second["run_id"])

    def test_state_json_round_trip(self):
        state = create_initial_state("Question", make_config("Question"))

        payload = state_to_json(state)
        restored = state_from_json(payload)

        self.assertEqual(restored, state)
        self.assertEqual(json.loads(payload)["current_step"], "initialized")
        self.assertEqual(json.loads(payload)["next_action"], "retrieve")

    def test_document_and_analysis_mapping_is_valid(self):
        analysis, document = make_analysis()
        state = create_initial_state(
            analysis.research_problem,
            make_config(analysis.research_problem),
        )
        key = str(document.paper_id)
        state["documents"] = {key: document}
        state["analyses"] = {key: analysis}

        validated = validate_state(state)

        self.assertEqual(validated["documents"][key].paper_id, document.paper_id)
        self.assertIsInstance(validated["analyses"][key], PaperAnalysisResult)

    def test_populated_state_json_round_trip(self):
        analysis, document = make_analysis()
        state = create_initial_state(
            analysis.research_problem,
            make_config(analysis.research_problem),
        )
        key = str(document.paper_id)
        state["documents"] = {key: document}
        state["analyses"] = {key: analysis}

        restored = state_from_json(state_to_json(state))

        self.assertEqual(restored["documents"][key], document)
        self.assertEqual(restored["analyses"][key], analysis)

    def test_question_mismatch_is_rejected(self):
        state = create_initial_state("Question", make_config("Question"))
        state["question"] = "Different question"

        with self.assertRaises(StateValidationError):
            validate_state(state)

    def test_invalid_document_key_is_rejected(self):
        _, document = make_analysis()
        state = create_initial_state("Question", make_config("Question"))
        state["documents"] = {"wrong-key": document}

        with self.assertRaises(StateValidationError):
            validate_state(state)

    def test_analysis_without_document_is_rejected(self):
        analysis, _ = make_analysis()
        state = create_initial_state("Question", make_config("Question"))
        state["analyses"] = {str(analysis.paper_id): analysis}

        with self.assertRaises(StateValidationError):
            validate_state(state)

    def test_duplicate_paper_ids_are_rejected(self):
        paper = make_paper()
        state = create_initial_state("Question", make_config("Question"))
        state["papers"] = [paper, paper.model_copy(deep=True)]

        with self.assertRaises(StateValidationError):
            validate_state(state)

    def test_negative_attempt_count_is_rejected(self):
        state = create_initial_state("Question", make_config("Question"))
        state["attempts"] = {"retrieval": -1}

        with self.assertRaises(StateValidationError):
            validate_state(state)

    def test_invalid_json_is_wrapped(self):
        with self.assertRaises(StateValidationError):
            state_from_json('{"question":')


if __name__ == "__main__":
    unittest.main()
