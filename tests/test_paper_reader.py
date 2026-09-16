"""Unit tests for evidence-grounded single-paper analysis orchestration."""

import unittest
from uuid import uuid4

from paperguide.analysis import (
    AnalysisLLMInvocationError,
    EvidenceMapper,
    EvidenceReference,
    ExperimentAnalysis,
    ExperimentMetricAnalysis,
    InsufficientEvidenceError,
    MethodAnalysis,
    PaperContextBuilder,
    PaperContextError,
    PaperReader,
    PaperReaderOutput,
)
from paperguide.document import Document, Page, Section


def make_document() -> Document:
    pages = [
        Page(page_number=1, text="Abstract\nWe study robust localization."),
        Page(
            page_number=2,
            text="Method\nThe method filters dynamic features before mapping.",
        ),
        Page(
            page_number=3,
            text="Experiments\nKITTI ATE is 0.12 m versus 0.20 m baseline.",
        ),
        Page(page_number=4, text="Conclusion\nCode is not publicly available."),
    ]
    return Document(
        paper_id=uuid4(),
        title="Paper Reader Test",
        source_path="paper.pdf",
        pages=pages,
        sections=[
            Section(title="Abstract", page_start=1, page_end=1, text=pages[0].text),
            Section(title="Method", page_start=2, page_end=2, text=pages[1].text),
            Section(
                title="Experiments", page_start=3, page_end=3, text=pages[2].text
            ),
            Section(title="Conclusion", page_start=4, page_end=4, text=pages[3].text),
        ],
        metadata={"page_count": 4},
    )


def make_output(
    *,
    method_keys: list[str] | None = None,
    experiment_keys: list[str] | None = None,
    warning: str = "",
) -> PaperReaderOutput:
    return PaperReaderOutput(
        research_problem="Dynamic objects degrade visual localization.",
        contributions=["A detection and mapping fusion method."],
        method=MethodAnalysis(
            name="FusionSLAM",
            problem="Dynamic objects degrade visual localization.",
            summary="The method filters dynamic features before mapping.",
            architecture=["detector", "filter", "mapper"],
            innovations=["Dynamic-feature filtering"],
            limitations=["Code is unavailable", "Outdoor evaluation only"],
            evidence_keys=method_keys if method_keys is not None else ["E1"],
            confidence=0.9,
        ),
        experiments=ExperimentAnalysis(
            objective="Evaluate trajectory accuracy.",
            datasets=["KITTI"],
            baselines=["ORB-SLAM3"],
            metrics=[
                ExperimentMetricAnalysis(
                    dataset="KITTI",
                    metric="ATE",
                    value="0.12 m",
                    baseline="0.20 m",
                    comparison="lower than baseline",
                    evidence_keys=["E2"],
                    confidence=0.85,
                ),
                ExperimentMetricAnalysis(
                    dataset="KITTI",
                    metric="ATE",
                    value="0.11 m",
                    baseline=None,
                    comparison="second sequence",
                    evidence_keys=["E2"],
                    confidence=0.8,
                ),
            ],
            findings=["ATE is lower than the baseline."],
            reproducibility_notes=["Code is unavailable."],
            evidence_keys=(
                experiment_keys if experiment_keys is not None else ["E2"]
            ),
            confidence=0.85,
        ),
        limitations=["Code is unavailable"],
        evidence=[
            EvidenceReference(
                evidence_key="E1",
                quote="The method filters dynamic features before mapping.",
                page_number=2,
                section_title="Method",
                claim="The method filters dynamic features before mapping.",
                confidence=0.95,
            ),
            EvidenceReference(
                evidence_key="E2",
                quote="KITTI ATE is 0.12 m versus 0.20 m baseline.",
                page_number=3,
                section_title="Experiments",
                claim="ATE is 0.12 m against a 0.20 m baseline.",
                confidence=0.95,
            ),
        ],
        analysis_warnings=[warning, warning] if warning else [],
        confidence=0.88,
    )


class FakeStructuredLLM:
    """Synchronous structured LLM returning a fixed validated output."""

    model_name = "fake-reader-model"

    def __init__(self, output: PaperReaderOutput):
        self.output = output
        self.calls = []

    def generate_structured(self, *, system_prompt, user_prompt, response_model):
        self.calls.append((system_prompt, user_prompt, response_model))
        return self.output.model_copy(deep=True)


class FailingLLM:
    def generate_structured(self, **kwargs):
        raise AnalysisLLMInvocationError("LLM unavailable")


class FailingContextBuilder:
    def build(self, document):
        raise ValueError("broken context")


class TestPaperReader(unittest.TestCase):
    def _reader(self, output: PaperReaderOutput | None = None):
        llm = FakeStructuredLLM(output or make_output())
        return PaperReader(llm, PaperContextBuilder(), EvidenceMapper()), llm

    def test_complete_fake_llm_analysis_succeeds(self):
        reader, llm = self._reader()

        result = reader.analyze(make_document())

        self.assertEqual(result.research_problem, "Dynamic objects degrade visual localization.")
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual(len(llm.calls), 1)

    def test_method_summary_is_generated(self):
        result = self._reader()[0].analyze(make_document())

        self.assertEqual(result.method_summary.name, "FusionSLAM")
        self.assertIn("Dynamic-feature filtering", result.method_summary.innovations)
        self.assertEqual(
            result.method_summary.limitations,
            ["Code is unavailable", "Outdoor evaluation only"],
        )

    def test_experiment_summary_is_generated(self):
        result = self._reader()[0].analyze(make_document())

        self.assertEqual(result.experiment_summary.datasets, ["KITTI"])
        self.assertEqual(result.experiment_summary.baselines, ["ORB-SLAM3"])
        self.assertEqual(
            list(result.experiment_summary.metrics), ["KITTI:ATE", "KITTI:ATE#2"]
        )

    def test_evidence_ids_are_written_to_summaries(self):
        result = self._reader()[0].analyze(make_document())
        evidence_by_claim = {item.normalized_fact: item.id for item in result.evidence}

        self.assertEqual(
            result.method_summary.evidence_ids,
            [evidence_by_claim["The method filters dynamic features before mapping."]],
        )
        self.assertEqual(
            result.experiment_summary.evidence_ids,
            [evidence_by_claim["ATE is 0.12 m against a 0.20 m baseline."]],
        )

    def test_unknown_experiment_evidence_key_adds_warning(self):
        output = make_output(experiment_keys=["E2", "MISSING"])

        result = self._reader(output)[0].analyze(make_document())

        self.assertTrue(any("MISSING" in warning for warning in result.warnings))
        self.assertEqual(len(result.experiment_summary.evidence_ids), 1)

    def test_rejected_method_evidence_causes_failure(self):
        output = make_output(method_keys=["MISSING"])

        with self.assertRaises(InsufficientEvidenceError):
            self._reader(output)[0].analyze(make_document())

    def test_unlocatable_method_quote_causes_failure(self):
        output = make_output()
        evidence = list(output.evidence)
        evidence[0] = evidence[0].model_copy(update={"quote": "fabricated quote"})
        output = output.model_copy(update={"evidence": evidence})

        with self.assertRaises(InsufficientEvidenceError):
            self._reader(output)[0].analyze(make_document())

    def test_llm_failure_is_preserved_as_typed_error(self):
        reader = PaperReader(FailingLLM(), PaperContextBuilder(), EvidenceMapper())

        with self.assertRaises(AnalysisLLMInvocationError):
            reader.analyze(make_document())

    def test_context_failure_is_wrapped(self):
        reader = PaperReader(FakeStructuredLLM(make_output()), FailingContextBuilder(), EvidenceMapper())

        with self.assertRaises(PaperContextError) as context:
            reader.analyze(make_document())
        self.assertNotIn("broken context", str(context.exception))

    def test_document_is_not_modified(self):
        document = make_document()
        before = document.model_dump(mode="json")

        self._reader()[0].analyze(document)

        self.assertEqual(document.model_dump(mode="json"), before)

    def test_warnings_are_stably_deduplicated(self):
        output = make_output(warning="Metric uncertainty remains.")

        result = self._reader(output)[0].analyze(make_document())

        self.assertEqual(result.warnings.count("Metric uncertainty remains."), 1)

    def test_prompt_version_and_model_name_are_recorded(self):
        result = self._reader()[0].analyze(make_document())

        self.assertEqual(result.prompt_version, "v3")
        self.assertEqual(result.model_name, "fake-reader-model")

    def test_prompt_contains_controlled_context_and_schema_contract(self):
        reader, llm = self._reader()

        reader.analyze(make_document())

        system_prompt, user_prompt, response_model = llm.calls[0]
        self.assertIn("Use only the supplied paper context", system_prompt)
        self.assertIn("Simplified Chinese", system_prompt)
        self.assertIn("evidence quote in its original language", system_prompt)
        self.assertIn("[PAGE 2][SECTION Method]", user_prompt)
        self.assertIn("at most 10 evidence entries", user_prompt)
        self.assertIn("semantically supported by its exact quote", user_prompt)
        self.assertIn("verbatim quote under", user_prompt)
        self.assertIn("500 characters", user_prompt)
        self.assertIs(response_model, PaperReaderOutput)


if __name__ == "__main__":
    unittest.main()
