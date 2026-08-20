"""Unit tests for the minimal PaperPilot domain models."""

import unittest
from uuid import UUID

from pydantic import ValidationError

from paperpilot.domain import (
    Author,
    Evidence,
    EvidenceType,
    ExperimentSummary,
    FullTextStatus,
    MethodSummary,
    PaperCandidate,
    PaperSource,
    ResearchConfig,
    SourceLocator,
)


def make_paper(**overrides) -> PaperCandidate:
    values = {
        "title": "YOLO-SLAM: A Visual SLAM System",
        "normalized_title": "yolo slam a visual slam system",
        "abstract": "A system combining object detection and visual SLAM.",
        "authors": [
            Author(full_name="Ada Researcher", affiliations=["AI Laboratory"])
        ],
        "publication_year": 2025,
        "venue": "ICRA",
        "sources": [PaperSource.ARXIV, PaperSource.SEMANTIC_SCHOLAR],
        "full_text_status": FullTextStatus.AVAILABLE,
        "relevance_score": 0.91,
    }
    values.update(overrides)
    return PaperCandidate(**values)


class TestPaperPilotDomain(unittest.TestCase):
    def test_paper_candidate_can_be_created(self):
        paper = make_paper()

        self.assertEqual(paper.title, "YOLO-SLAM: A Visual SLAM System")
        self.assertEqual(paper.authors[0].full_name, "Ada Researcher")
        self.assertEqual(paper.publication_year, 2025)
        self.assertIs(paper.full_text_status, FullTextStatus.AVAILABLE)

    def test_uuid_is_generated_automatically(self):
        first = make_paper()
        second = make_paper()

        self.assertIsInstance(first.id, UUID)
        self.assertNotEqual(first.id, second.id)

    def test_relevance_score_outside_range_is_rejected(self):
        for score in (-0.01, 1.01):
            with self.subTest(score=score), self.assertRaises(ValidationError):
                make_paper(relevance_score=score)

    def test_max_papers_outside_range_is_rejected(self):
        for max_papers in (0, 51):
            with self.subTest(max_papers=max_papers), self.assertRaises(
                ValidationError
            ):
                ResearchConfig(
                    question="Analyze YOLO and SLAM research",
                    sources=[PaperSource.ARXIV],
                    max_papers=max_papers,
                )

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            Author(full_name="Ada Researcher", affiliations=[], unknown="value")

    def test_evidence_and_source_locator_can_be_nested(self):
        paper = make_paper()
        locator = SourceLocator(
            paper_id=paper.id,
            section_title="Experiments",
            page_start=7,
            page_end=8,
            paragraph_index=2,
            char_start=120,
            char_end=245,
        )
        evidence = Evidence(
            paper_id=paper.id,
            evidence_type=EvidenceType.DIRECT,
            quote="The proposed method improves tracking accuracy by 8%.",
            normalized_fact="Tracking accuracy improved by 8%.",
            locator=locator,
            confidence=0.98,
        )

        self.assertEqual(evidence.locator.paper_id, paper.id)
        self.assertEqual(evidence.locator.section_title, "Experiments")

    def test_enums_serialize_to_their_values(self):
        paper = make_paper()
        serialized = paper.model_dump(mode="json")

        self.assertEqual(serialized["sources"], ["arxiv", "semantic_scholar"])
        self.assertEqual(serialized["full_text_status"], "available")

    def test_model_json_round_trip(self):
        paper = make_paper(doi="10.1000/example")

        restored = PaperCandidate.model_validate_json(paper.model_dump_json())

        self.assertEqual(restored, paper)
        self.assertIsInstance(restored.id, UUID)
        self.assertEqual(
            restored.sources,
            [PaperSource.ARXIV, PaperSource.SEMANTIC_SCHOLAR],
        )

    def test_method_and_experiment_summaries_can_be_created(self):
        paper = make_paper()
        evidence_id = Evidence(
            paper_id=paper.id,
            evidence_type=EvidenceType.DIRECT,
            quote="The model was evaluated on KITTI.",
            normalized_fact="The evaluation used KITTI.",
            locator=SourceLocator(paper_id=paper.id, section_title="Experiments"),
            confidence=0.95,
        ).id

        method = MethodSummary(
            paper_id=paper.id,
            name="YOLO-SLAM",
            problem="Dynamic objects reduce SLAM robustness.",
            summary="The method filters dynamic objects before pose estimation.",
            innovations=["Object-aware feature filtering"],
            limitations=["Depends on detector accuracy"],
            evidence_ids=[evidence_id],
            confidence=0.9,
        )
        experiment = ExperimentSummary(
            paper_id=paper.id,
            datasets=["KITTI"],
            metrics={"ATE": "0.12 m"},
            baselines=["ORB-SLAM3"],
            findings=["Lower ATE in dynamic scenes"],
            evidence_ids=[evidence_id],
            confidence=0.88,
        )

        self.assertEqual(method.evidence_ids, [evidence_id])
        self.assertEqual(experiment.metrics, {"ATE": "0.12 m"})

    def test_evidence_rejects_mismatched_locator_paper(self):
        paper = make_paper()
        other_paper = make_paper()

        with self.assertRaises(ValidationError):
            Evidence(
                paper_id=paper.id,
                evidence_type=EvidenceType.DIRECT,
                quote="Reported experimental result.",
                normalized_fact="The experiment reported a result.",
                locator=SourceLocator(paper_id=other_paper.id),
                confidence=0.8,
            )

    def test_research_year_range_is_validated(self):
        with self.assertRaises(ValidationError):
            ResearchConfig(
                question="Analyze recent research",
                start_year=2026,
                end_year=2024,
                sources=[PaperSource.OPENALEX],
            )


if __name__ == "__main__":
    unittest.main()
