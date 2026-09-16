import pytest

from paperguide.analysis import AnalysisSchemaValidationError, EvidenceLinkingService
from paperguide.demo import FakeReader, FakeVerifier, create_demo_seed
from paperguide.relevance import ReportMode
from paperguide.reporting import (
    ComparisonDataBuilder,
    DeterministicTaxonomyBuilder,
    FullSurveySynthesisService,
    MethodFamilyAssignment,
    SurveyEvidenceDataBuilder,
    SurveyParagraphDraft,
    SurveyReportContextBuilder,
    SurveyStageDraft,
    SurveyClaimDraft,
    SurveyClaimType,
    ClaimCertainty,
    SurveySynthesisWriter,
    SynthesisStage,
    TaxonomyContextBuilder,
)
from paperguide.verification import apply_verification


def make_fixture(mode=ReportMode.FULL_SURVEY):
    seed = create_demo_seed()
    linked, verified = {}, {}
    for index, paper in enumerate(seed.papers):
        analysis = FakeReader().analyze(seed.documents[index])
        result = apply_verification(analysis, FakeVerifier().verify(analysis, seed.documents[index]))
        linked[str(paper.id)] = EvidenceLinkingService().link(analysis, result, paper)
        verified[str(paper.id)] = result
    evidence = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    context = SurveyReportContextBuilder().build("demo research question", evidence, mode)
    context = context.model_copy(
        update={"warnings": [*context.warnings, "DEMO_PREVIEW_DATA"]}
    )
    taxonomy = DeterministicTaxonomyBuilder().build(TaxonomyContextBuilder().build(evidence))
    analysis_data = ComparisonDataBuilder().build(evidence, seed.papers, linked, verified, taxonomy)
    return context, evidence, analysis_data


class FakeStageLLM:
    def __init__(self, invalid_key=False):
        self.calls = 0
        self.invalid_key = invalid_key

    def generate_structured(self, *, user_prompt, **kwargs):
        self.calls += 1
        stage = next(value for value in SynthesisStage if f"stage {value.value}" in user_prompt)
        key = "unknown" if self.invalid_key else ""
        return SurveyStageDraft(stage=stage, title=f"Stage {stage.value}", paragraphs=[SurveyParagraphDraft(text="Evidence-bounded synthesis.", source_statement_keys=[] if not key else [key])], claims=[])


class FakeChineseStageLLM:
    def generate_structured(self, *, user_prompt, **kwargs):
        stage = next(value for value in SynthesisStage if f"stage {value.value}" in user_prompt)
        return SurveyStageDraft(
            stage=stage,
            title=f"阶段 {stage.value}：证据驱动综述",
            paragraphs=[SurveyParagraphDraft(text="本节仅综合当前已经验证的论文证据。")],
            claims=[],
        )


def test_full_survey_uses_four_bounded_calls_and_structured_sections():
    context, evidence, analysis_data = make_fixture()
    llm = FakeStageLLM()
    report = FullSurveySynthesisService(SurveySynthesisWriter(llm)).generate(context, evidence, analysis_data)
    assert llm.calls == 4
    assert [item.number for item in report.sections] == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
    assert report.figures[0].figure_type == "LITERATURE_TIMELINE_FISHBONE"
    assert report.tables[0].table_type == "COMPARISON_MATRIX"


def test_limited_review_is_shorter_and_warns():
    context, evidence, analysis_data = make_fixture(ReportMode.EVIDENCE_LIMITED_REVIEW)
    report = FullSurveySynthesisService(SurveySynthesisWriter(FakeStageLLM())).generate(context, evidence, analysis_data)
    assert [item.number for item in report.sections] == ["1", "2", "3", "4", "6", "8", "9", "10"]
    assert any("Verified literature coverage is limited" in warning for warning in report.warnings)


def test_writer_rejects_stage_mismatch():
    context, _, analysis_data = make_fixture()
    class Bad:
        def generate_structured(self, **kwargs):
            return SurveyStageDraft(stage=SynthesisStage.D, title="bad")
    with pytest.raises(Exception, match="STAGE"):
        SurveySynthesisWriter(Bad()).write(context, analysis_data)


def test_no_unknown_statement_key_enters_report():
    context, evidence, analysis_data = make_fixture()
    with pytest.raises(Exception):
        FullSurveySynthesisService(SurveySynthesisWriter(FakeStageLLM(invalid_key=True))).generate(context, evidence, analysis_data)


def test_report_public_view_hides_internal_statement_keys():
    context, evidence, analysis_data = make_fixture()
    report = FullSurveySynthesisService(SurveySynthesisWriter(FakeStageLLM())).generate(context, evidence, analysis_data)
    text = str(report.public_dict())
    assert "source_statement_keys" not in text
    assert "paper_id" not in text


def test_synthesis_does_not_modify_inputs():
    context, evidence, analysis_data = make_fixture()
    before = context.model_dump_json()
    FullSurveySynthesisService(SurveySynthesisWriter(FakeStageLLM())).generate(context, evidence, analysis_data)
    assert context.model_dump_json() == before


def test_missing_comparison_data_remains_in_analysis_layer():
    _, _, analysis_data = make_fixture()
    assert analysis_data.comparison_matrix.rows
    assert all("Dataset" not in str(row.cells) or row.cells for row in analysis_data.comparison_matrix.rows)


def test_chinese_question_produces_chinese_report_contract():
    context, evidence, analysis_data = make_fixture()
    context = context.model_copy(update={"research_question": "目标检测与视觉 SLAM 融合研究进展", "query_language": "zh"})
    report = FullSurveySynthesisService(SurveySynthesisWriter(FakeChineseStageLLM())).generate(context, evidence, analysis_data)
    assert "SLAM 研究综述" in report.title
    assert report.title.endswith("证据评估")
    assert [section.title for section in report.sections][:3] == ["引言", "文献检索与筛选方法", "研究背景与关键技术"]
    assert all(label in report.abstract for label in ("背景：", "方法：", "结果：", "局限："))


def test_stage_title_is_not_published_and_paragraph_is_not_duplicated():
    context, evidence, analysis_data = make_fixture()
    report = FullSurveySynthesisService(
        SurveySynthesisWriter(FakeStageLLM())
    ).generate(context, evidence, analysis_data)
    assert "Stage A" not in report.title
    assert report.title.startswith(context.research_question)
    assert sum(
        paragraph.text == "Evidence-bounded synthesis."
        for section in report.sections
        for paragraph in section.paragraphs
    ) == 1
    assert report.abstract.count("Evidence-bounded synthesis.") == 0


def test_chinese_question_rejects_english_only_writer_output():
    context, _, analysis_data = make_fixture()
    context = context.model_copy(update={"research_question": "目标检测与视觉 SLAM 融合研究进展", "query_language": "zh"})
    with pytest.raises(Exception, match="SURVEY_OUTPUT_LANGUAGE_MISMATCH"):
        SurveySynthesisWriter(FakeStageLLM()).write(context, analysis_data)


def test_unsupported_llm_claim_is_dropped_without_weakening_evidence_rules():
    context, evidence, analysis_data = make_fixture()

    class UnsupportedClaimLLM(FakeStageLLM):
        def generate_structured(self, *, user_prompt, **kwargs):
            draft = super().generate_structured(user_prompt=user_prompt, **kwargs)
            if draft.stage is SynthesisStage.A:
                return draft.model_copy(update={
                    "claims": [SurveyClaimDraft(
                        text="An unsupported generated conclusion.",
                        claim_type=SurveyClaimType.FINDING,
                        certainty=ClaimCertainty.HIGH,
                        source_statement_keys=[],
                    )]
                })
            return draft

    report = FullSurveySynthesisService(SurveySynthesisWriter(UnsupportedClaimLLM())).generate(context, evidence, analysis_data)
    assert not report.claims
    assert "UNSUPPORTED_SURVEY_CLAIM_DROPPED" in report.warnings


def test_provider_prose_with_internal_uuid_is_excluded_before_public_report():
    context, evidence, analysis_data = make_fixture()

    class LeakingStageLLM(FakeStageLLM):
        def generate_structured(self, *, user_prompt, **kwargs):
            draft = super().generate_structured(user_prompt=user_prompt, **kwargs)
            if draft.stage is SynthesisStage.A:
                return draft.model_copy(
                    update={
                        "paragraphs": [
                            SurveyParagraphDraft(
                                text="Safe evidence-bounded synthesis."
                            ),
                            SurveyParagraphDraft(
                                text="Internal 550e8400-e29b-41d4-a716-446655440000"
                            ),
                        ]
                    }
                )
            return draft

    report = FullSurveySynthesisService(
        SurveySynthesisWriter(LeakingStageLLM())
    ).generate(context, evidence, analysis_data)

    public_text = str(report.public_dict())
    assert "550e8400-e29b-41d4-a716-446655440000" not in public_text
    assert "Safe evidence-bounded synthesis." in public_text
    assert any("private linkage metadata" in warning for warning in report.warnings)

def test_writer_retries_one_schema_validation_failure():
    context, _, analysis_data = make_fixture()

    class SchemaThenValidLLM:
        def __init__(self):
            self.calls = 0
            self.system_prompts = []

        def generate_structured(self, *, system_prompt, user_prompt, **kwargs):
            self.calls += 1
            self.system_prompts.append(system_prompt)
            if self.calls == 1:
                raise AnalysisSchemaValidationError("invalid provider schema")
            stage = next(
                value
                for value in SynthesisStage
                if f"stage {value.value}" in user_prompt
            )
            return SurveyStageDraft(
                stage=stage,
                title=f"Stage {stage.value}",
                paragraphs=[
                    SurveyParagraphDraft(text="Evidence-bounded synthesis.")
                ],
            )

    llm = SchemaThenValidLLM()
    drafts = SurveySynthesisWriter(llm).write(context, analysis_data)

    assert len(drafts) == 4
    assert llm.calls == 5
    assert "previous response failed schema validation" in llm.system_prompts[1]

def test_repeated_schema_failures_use_deterministic_evidence_fallback():
    context, evidence, analysis_data = make_fixture()

    class AlwaysInvalidSchemaLLM:
        def __init__(self):
            self.calls = 0

        def generate_structured(self, **kwargs):
            self.calls += 1
            raise AnalysisSchemaValidationError("invalid provider schema")

    llm = AlwaysInvalidSchemaLLM()
    report = FullSurveySynthesisService(SurveySynthesisWriter(llm)).generate(
        context, evidence, analysis_data
    )

    assert llm.calls == 8
    assert len(report.sections) == 10
    assert all(section.paragraphs for section in report.sections)
    assert any("deterministic evidence summary" in warning for warning in report.warnings)
    assert report.references
    assert report.evidence_appendix

def test_provider_authored_citation_tokens_are_rebuilt_from_evidence_keys():
    context, evidence, analysis_data = make_fixture()
    valid_key = context.allowed_statement_keys[0]

    class HandwrittenCitationLLM(FakeStageLLM):
        def generate_structured(self, *, user_prompt, **kwargs):
            draft = super().generate_structured(user_prompt=user_prompt, **kwargs)
            if draft.stage is SynthesisStage.A:
                return draft.model_copy(
                    update={
                        "claims": [
                            SurveyClaimDraft(
                                text="A supported finding with a wrong token [999].",
                                claim_type=SurveyClaimType.FINDING,
                                source_statement_keys=[valid_key],
                            )
                        ],
                        "paragraphs": [
                            SurveyParagraphDraft(
                                text="Evidence-bounded paragraph [999].",
                                section_type="introduction",
                                source_statement_keys=[valid_key],
                            )
                        ],
                    }
                )
            return draft

    report = FullSurveySynthesisService(
        SurveySynthesisWriter(HandwrittenCitationLLM())
    ).generate(context, evidence, analysis_data)

    public_text = str(report.public_dict())
    assert "[999]" not in public_text
    assert report.claims[0].citation_tokens
    assert all("999" not in token for token in report.claims[0].citation_tokens)
    assert any("rebuilt from evidence keys" in warning for warning in report.warnings)
