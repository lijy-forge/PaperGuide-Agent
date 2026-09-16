"""Unit tests for structured Paper Reader analysis contracts."""

import unittest
from uuid import uuid4

from pydantic import ValidationError

from paperguide.analysis import (
    EvidenceReference,
    ExperimentAnalysis,
    ExperimentMetricAnalysis,
    MethodAnalysis,
    PaperAnalysisResult,
    PaperReaderOutput,
)
from paperguide.domain import (
    Evidence,
    EvidenceType,
    ExperimentSummary,
    MethodSummary,
    SourceLocator,
)


def make_reader_output() -> PaperReaderOutput:
    return PaperReaderOutput(
        research_problem="Improve robust visual localization.",
        contributions=["A fused detection and mapping architecture."],
        method=MethodAnalysis(
            name="FusionNet",
            problem="Dynamic objects degrade localization.",
            summary="The method filters dynamic features before mapping.",
            architecture=["detector", "feature filter", "mapper"],
            innovations=["Confidence-weighted feature filtering"],
            limitations=["Evaluated only outdoors"],
            evidence_keys=["E1"],
            confidence=0.9,
        ),
        experiments=ExperimentAnalysis(
            objective="Measure localization accuracy.",
            datasets=["KITTI"],
            baselines=["ORB-SLAM3"],
            metrics=[
                ExperimentMetricAnalysis(
                    dataset="KITTI",
                    metric="ATE",
                    value="0.12 m",
                    baseline="0.20 m",
                    comparison="lower is better",
                    evidence_keys=["E2"],
                    confidence=0.8,
                )
            ],
            findings=["ATE improved on KITTI."],
            reproducibility_notes=[],
            evidence_keys=["E2"],
            confidence=0.8,
        ),
        limitations=["Source code is unavailable"],
        evidence=[
            EvidenceReference(
                evidence_key="E1",
                quote="filters dynamic features",
                page_number=2,
                section_title="Method",
                claim="The method filters dynamic features.",
                confidence=0.95,
            )
        ],
        analysis_warnings=[],
        confidence=0.85,
    )


class TestAnalysisModels(unittest.TestCase):
    def test_paper_reader_output_can_be_created(self):
        output = make_reader_output()

        self.assertEqual(output.method.name, "FusionNet")
        self.assertEqual(output.experiments.datasets, ["KITTI"])

    def test_confidence_out_of_range_is_rejected(self):
        data = make_reader_output().model_dump()
        data["confidence"] = 1.1

        with self.assertRaises(ValidationError):
            PaperReaderOutput.model_validate(data)

    def test_nested_confidence_out_of_range_is_rejected(self):
        data = make_reader_output().model_dump()
        data["method"]["confidence"] = -0.1

        with self.assertRaises(ValidationError):
            PaperReaderOutput.model_validate(data)

    def test_unknown_fields_are_rejected(self):
        data = make_reader_output().model_dump()
        data["provider"] = "unexpected"

        with self.assertRaises(ValidationError):
            PaperReaderOutput.model_validate(data)

    def test_evidence_reference_requires_nonempty_text(self):
        with self.assertRaises(ValidationError):
            EvidenceReference(
                evidence_key=" ",
                quote="quote",
                claim="claim",
                confidence=0.5,
            )

    def test_evidence_reference_page_must_be_positive(self):
        with self.assertRaises(ValidationError):
            EvidenceReference(
                evidence_key="E1",
                quote="quote",
                page_number=0,
                claim="claim",
                confidence=0.5,
            )

    def test_analysis_result_json_round_trip(self):
        paper_id = uuid4()
        evidence = Evidence(
            paper_id=paper_id,
            evidence_type=EvidenceType.DIRECT,
            quote="filters dynamic features",
            normalized_fact="The method filters dynamic features.",
            locator=SourceLocator(
                paper_id=paper_id,
                page_start=2,
                page_end=2,
                char_start=4,
                char_end=28,
            ),
            confidence=0.9,
        )
        result = PaperAnalysisResult(
            paper_id=paper_id,
            document_id=uuid4(),
            research_problem="Robust localization",
            contributions=["Feature filtering"],
            method_summary=MethodSummary(
                paper_id=paper_id,
                name="FusionNet",
                problem="Dynamic objects",
                summary="Filters dynamic features.",
                innovations=["Filtering"],
                limitations=[],
                evidence_ids=[evidence.id],
                confidence=0.9,
            ),
            experiment_summary=ExperimentSummary(
                paper_id=paper_id,
                datasets=[],
                metrics={},
                baselines=[],
                findings=[],
                evidence_ids=[],
                confidence=0.5,
            ),
            evidence=[evidence],
            limitations=[],
            warnings=[],
            confidence=0.8,
            model_name="fake-model",
            prompt_version="v1",
        )

        restored = PaperAnalysisResult.model_validate_json(result.model_dump_json())

        self.assertEqual(restored, result)

    def test_analysis_result_rejects_inconsistent_paper_id(self):
        paper_id = uuid4()
        with self.assertRaises(ValidationError):
            PaperAnalysisResult(
                paper_id=paper_id,
                document_id=uuid4(),
                research_problem="Problem",
                contributions=[],
                method_summary=MethodSummary(
                    paper_id=uuid4(),
                    summary="Method",
                    innovations=[],
                    limitations=[],
                    evidence_ids=[],
                    confidence=0.5,
                ),
                experiment_summary=ExperimentSummary(
                    paper_id=paper_id,
                    datasets=[],
                    metrics={},
                    baselines=[],
                    findings=[],
                    evidence_ids=[],
                    confidence=0.5,
                ),
                evidence=[],
                limitations=[],
                warnings=[],
                confidence=0.5,
                prompt_version="v1",
            )


if __name__ == "__main__":
    unittest.main()
