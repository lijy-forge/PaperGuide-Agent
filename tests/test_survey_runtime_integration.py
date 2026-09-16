"""Offline production-entry integration tests for the Survey runtime path."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from paperguide.analysis import EvidenceLinkingService
from paperguide.application import (
    InMemoryTaskStore,
    ResearchApplicationService,
    ResearchExecutionError,
    ResearchRequest,
)
from paperguide.demo import (
    DemoDocumentIngestionPipeline,
    FakeReader,
    FakeVerifier,
    create_demo_seed,
)
from paperguide.export import ExportFormat, ExportService
from paperguide.orchestration import (
    NextAction,
    OrchestratorConfig,
    ResearchError,
    ResearchStep,
    create_initial_state,
    create_research_graph,
)
from paperguide.orchestration.nodes import (
    IngestionNode,
    PlannerNode,
    QualityGateNode,
    ReaderNode,
    RetrieverNode,
    VerifierNode,
)
from paperguide.domain import ResearchConfig
from paperguide.pipeline import SearchResult
from paperguide.relevance import EvidenceAwareFinalRelevanceService
from paperguide.relevance import (
    AssessmentStatus,
    EvidenceSufficiencyAssessment,
    FinalRelevanceAssessment,
    FinalRelevanceClassification,
    ReportMode,
    QueryVariant,
    ResearchIntent,
    RetrievalBudget,
    RetrievalPlan,
)
from paperguide.reporting import (
    ProductionSurveyReportService,
    SurveyAnalysisDataBuilder,
    SurveyEvidenceDataBuilder,
    SurveyReport,
    SurveyReportContextBuilder,
    SurveySynthesisWriter,
)
from paperguide.reporting.synthesis import FullSurveySynthesisService, SynthesisStage
from paperguide.reporting import ReportSchemaValidationError, ReportGenerationError
from paperguide.verification import VerificationInputError, apply_verification
from tests.test_survey_synthesis import FakeChineseStageLLM


class _StageLLM:
    """Deterministic section writer; no provider call is made."""

    def __init__(self):
        self.calls = 0

    def generate_structured(self, *, user_prompt, **kwargs):
        from paperguide.reporting import SurveyParagraphDraft, SurveyStageDraft

        self.calls += 1
        stage = next(item for item in SynthesisStage if f"stage {item.value}" in user_prompt)
        return SurveyStageDraft(stage=stage, title="Survey integration report", paragraphs=[SurveyParagraphDraft(text="Evidence-bounded survey synthesis.")])


class _Graph:
    def __init__(self, state):
        self.state = state

    def invoke(self, _state):
        return deepcopy(self.state)


class _LegacyMustNotRun:
    def generate(self, *_args):
        raise AssertionError("legacy report generator must not run for survey state")


def _completed_state(mode: ReportMode):
    seed = create_demo_seed()
    question = "Analyze evidence-grounded visual SLAM research"
    state = create_initial_state(question, ResearchConfig(question=question, max_papers=3, sources=[]))
    linked, verified, analyses = {}, {}, {}
    for index, paper in enumerate(seed.papers):
        analysis = FakeReader().analyze(seed.documents[index])
        result = apply_verification(analysis, FakeVerifier().verify(analysis, seed.documents[index]))
        analyses[str(paper.id)] = analysis
        verified[str(paper.id)] = result
        linked[str(paper.id)] = EvidenceLinkingService().link(analysis, result, paper)
    assessments = {}
    for paper in seed.papers:
        assessments[str(paper.id)] = FinalRelevanceAssessment(
            paper_id=paper.id, final_classification=FinalRelevanceClassification.CORE,
            assessment_status=AssessmentStatus.ASSESSED, fulltext_concept_coverage=1,
            relation_evidence_strength=1, research_focus_match=1,
            verified_evidence_coverage=1, evidence_quality=1, conflict_penalty=0,
            overall_score=1, selected_for_report=True,
        )
    state.update({
        "papers": seed.papers, "documents": {str(item.paper_id): item for item in seed.documents},
        "analyses": analyses, "verified_results": verified,
        "verification_results": {key: value.verification for key, value in verified.items()},
        "evidence_linked_analysis": linked, "final_relevance": assessments,
        "evidence_sufficiency": EvidenceSufficiencyAssessment(
            core_paper_count=3, selected_core_paper_count=3, verified_evidence_count=6,
            relation_evidence_count=3, evidence_coverage_score=1, metadata_completeness_score=1,
            cross_paper_coverage=1, conflict_ratio=0, recommended_report_mode=mode,
        ),
        "report_mode": mode, "current_step": ResearchStep.QUALITY_GATE,
        "next_action": NextAction.COMPLETE,
    })
    return state


def _survey_service(llm):
    return ProductionSurveyReportService(
        SurveyEvidenceDataBuilder(), SurveyAnalysisDataBuilder(),
        SurveyReportContextBuilder(), FullSurveySynthesisService(SurveySynthesisWriter(llm)),
        deterministic_analysis=True,
    )


class _DeterministicPlanService:
    """Provide a Chinese intent while keeping the compiled graph fully real."""

    def build(self, question, *, max_core_papers):
        return RetrievalPlan(
            intent=ResearchIntent(
                research_question=question,
                required_concepts=["YOLO", "visual SLAM"],
                query_language="zh",
            ),
            query_variants=[QueryVariant(query="YOLO visual SLAM", purpose="direct")],
            budget=RetrievalBudget(max_core_papers=max_core_papers),
        )


class _DeterministicSearchPipeline:
    """Return controlled candidates through the real RetrieverNode boundary."""

    def __init__(self, papers, *, source_errors=None):
        self.papers = list(papers)
        self.source_errors = dict(source_errors or {})

    def search(self, _config):
        return SearchResult(
            papers=[item.model_copy(deep=True) for item in self.papers],
            source_results={"fixture": len(self.papers)},
            source_errors=self.source_errors,
            warnings=[],
            total_found=len(self.papers),
            total_after_dedup=len(self.papers),
        )


def _compiled_graph(
    *,
    papers,
    source_errors=None,
    apply_verification_fn=apply_verification,
    orchestrator_config=None,
):
    """Build the actual production topology with deterministic boundaries."""

    seed = create_demo_seed()
    return create_research_graph(
        PlannerNode(_DeterministicPlanService()),
        RetrieverNode(_DeterministicSearchPipeline(papers, source_errors=source_errors)),
        IngestionNode(DemoDocumentIngestionPipeline(seed)),
        ReaderNode(FakeReader()),
        VerifierNode(
            FakeVerifier(),
            apply_verification_fn=apply_verification_fn,
            final_relevance_service=EvidenceAwareFinalRelevanceService(),
            evidence_linking_service=EvidenceLinkingService(),
        ),
        QualityGateNode(orchestrator_config or OrchestratorConfig()),
    )


def _compiled_state(graph, question):
    config = ResearchConfig(question=question, max_papers=3, sources=[])
    return graph.invoke(create_initial_state(question, config))


def _compiled_application(graph, llm, output_directory):
    return ResearchApplicationService(
        graph,
        _LegacyMustNotRun(),
        ExportService(output_directory),
        InMemoryTaskStore(),
        survey_report_generator=_survey_service(llm),
    )


def test_production_application_uses_survey_not_legacy_and_exports_all_formats():
    llm = _StageLLM()
    state = _completed_state(ReportMode.FULL_SURVEY)
    with TemporaryDirectory() as directory:
        app = ResearchApplicationService(
            _Graph(state), _LegacyMustNotRun(), ExportService(Path(directory)),
            InMemoryTaskStore(), survey_report_generator=_survey_service(llm),
        )
        for export_format in (ExportFormat.MARKDOWN, ExportFormat.HTML, ExportFormat.PDF):
            result = app.run(ResearchRequest(question=state["question"], max_papers=3, export_format=export_format))
            assert isinstance(result.report, SurveyReport)
            assert Path(result.export_result.file_path).is_file()
            assert result.report.report_mode is ReportMode.FULL_SURVEY
        assert llm.calls == 12  # exactly four bounded synthesis calls per requested artifact


def test_production_survey_consumes_evidence_limited_mode():
    state = _completed_state(ReportMode.EVIDENCE_LIMITED_REVIEW)
    report = _survey_service(_StageLLM()).generate(state)
    assert report.report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW
    assert [section.number for section in report.sections] == ["1", "2", "3", "4", "6", "8", "9", "10"]


def test_partial_verification_failure_uses_survey_handoff_and_exports_artifact():
    """One paper-level verification failure must not fall back to Legacy Writer."""

    state = _completed_state(ReportMode.EVIDENCE_LIMITED_REVIEW)
    state["next_action"] = NextAction.COMPLETE_DEGRADED
    failed_paper = state["papers"][0]
    state["errors"] = [
        ResearchError(
            stage=ResearchStep.VERIFICATION,
            paper_id=failed_paper.id,
            error_type="VerificationInputError",
            message="one paper could not retain verified evidence",
            recoverable=True,
            attempt=0,
        )
    ]

    assert ResearchApplicationService._is_survey_terminal_state(state) is True

    with TemporaryDirectory() as directory:
        result = ResearchApplicationService(
            _Graph(state),
            _LegacyMustNotRun(),
            ExportService(Path(directory)),
            InMemoryTaskStore(),
            survey_report_generator=_survey_service(_StageLLM()),
        ).run(
            ResearchRequest(
                question=state["question"],
                max_papers=3,
                export_format=ExportFormat.PDF,
            )
        )
        artifact_bytes = Path(result.export_result.file_path).read_bytes()

    assert isinstance(result.report, SurveyReport)
    assert result.report.report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW
    assert result.export_result is not None
    assert result.export_result.artifact is not None
    assert result.export_result.file_path.endswith(".pdf")
    assert artifact_bytes.startswith(b"%PDF-")
    assert result.task.status.value == "completed"
    # The source state remains auditable; the item failure is not discarded.
    assert len(state["errors"]) == 1
    assert state["errors"][0].paper_id == failed_paper.id


def test_compiled_partial_apply_failure_reaches_evidence_limited_survey():
    """The real VerifierNode must keep one failed item from blocking Survey."""

    class _FailFirstApply:
        def __init__(self):
            self.calls = 0

        def __call__(self, analysis, verification):
            self.calls += 1
            if self.calls % 3 == 1:
                raise VerificationInputError("one paper cannot retain evidence")
            return apply_verification(analysis, verification)

    seed = create_demo_seed()
    failing_apply = _FailFirstApply()
    graph = _compiled_graph(
        papers=seed.papers[:2],
        apply_verification_fn=failing_apply,
        orchestrator_config=OrchestratorConfig(minimum_verified_papers=2),
    )
    question = "Analyze evidence-grounded visual SLAM research"
    state = _compiled_state(graph, question)

    assert state["next_action"] is NextAction.COMPLETE_DEGRADED
    assert state["report_mode"] is ReportMode.EVIDENCE_LIMITED_REVIEW
    assert len(state["verified_results"]) == 1
    assert len(state["errors"]) == 1
    assert state["errors"][0].recoverable is True
    assert ResearchApplicationService._is_survey_terminal_state(state) is True

    with TemporaryDirectory() as directory:
        result = _compiled_application(
            graph, FakeChineseStageLLM(), Path(directory)
        ).run(
            ResearchRequest(
                question=question,
                max_papers=3,
                export_format=ExportFormat.PDF,
            )
        )
        artifact_bytes = Path(result.export_result.file_path).read_bytes()

    assert isinstance(result.report, SurveyReport)
    assert result.report.report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW
    assert result.task.status.value == "completed"
    assert artifact_bytes.startswith(b"%PDF-")


def test_production_survey_uses_planned_chinese_locale_for_limited_pdf():
    question = "目标检测与视觉 SLAM 融合研究进展"
    state = _completed_state(ReportMode.EVIDENCE_LIMITED_REVIEW)
    state["question"] = question
    state["research_config"] = state["research_config"].model_copy(
        update={"question": question}
    )
    state["retrieval_plan"] = RetrievalPlan(
        intent=ResearchIntent(
            research_question=question,
            required_concepts=["目标检测", "视觉 SLAM"],
            query_language="zh",
        ),
        query_variants=[QueryVariant(query="visual SLAM object detection", purpose="direct")],
        budget=RetrievalBudget(max_core_papers=3),
    )
    report = _survey_service(FakeChineseStageLLM()).generate(state)
    assert report.query_language == "zh"
    assert "SLAM 研究综述" in report.title
    assert report.title.endswith("证据评估")
    from paperguide.reporting import SurveyPdfRenderer
    import pymupdf

    document = pymupdf.open(stream=SurveyPdfRenderer().render(report), filetype="pdf")
    try:
        text = "\n".join(page.get_text() for page in document).replace("\xa0", " ")
    finally:
        document.close()
    assert "SLAM" in text
    assert "结构化摘要" in text
    assert "摘要" in text and "研究背景与关键技术" in text


def test_production_survey_preserves_safe_failure_type_and_code():
    class FailingSynthesis:
        def generate(self, *_args):
            raise ReportSchemaValidationError("SURVEY_OUTPUT_LANGUAGE_MISMATCH")

    service = ProductionSurveyReportService(
        SurveyEvidenceDataBuilder(), SurveyAnalysisDataBuilder(),
        SurveyReportContextBuilder(), FailingSynthesis(),
        deterministic_analysis=True,
    )

    with pytest.raises(ReportGenerationError, match="ReportSchemaValidationError:SURVEY_OUTPUT_LANGUAGE_MISMATCH"):
        service.generate(_completed_state(ReportMode.FULL_SURVEY))


def test_compiled_graph_limited_abort_is_not_promoted_without_auditable_source():
    """A no-evidence limited Survey is executable but not a formal artifact."""

    question = "目标检测与视觉SLAM融合研究进展"
    graph = _compiled_graph(papers=[])
    state = _compiled_state(graph, question)

    assert state["current_step"] is ResearchStep.QUALITY_GATE
    assert state["next_action"] is NextAction.ABORT
    assert state["report_mode"] is ReportMode.EVIDENCE_LIMITED_REVIEW
    assert state["errors"] == []

    with TemporaryDirectory() as directory:
        result = _compiled_application(
            graph, FakeChineseStageLLM(), Path(directory)
        ).run(
            ResearchRequest(
                question=question,
                max_papers=3,
                export_format=ExportFormat.PDF,
            )
        )

    assert result.task.status.value == "failed"
    assert isinstance(result.report, SurveyReport)
    assert result.report.report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW
    assert result.export_result is None
    assert result.task.error == "REPORT_QUALITY_REJECTED"


def test_compiled_graph_full_survey_uses_survey_handoff():
    """A sufficient compiled graph state enters Survey rather than legacy writer."""

    question = "目标检测与视觉SLAM融合研究进展"
    seed = create_demo_seed()
    graph = _compiled_graph(papers=seed.papers)
    state = _compiled_state(graph, question)

    assert state["next_action"] is NextAction.COMPLETE
    assert state["report_mode"] is ReportMode.FULL_SURVEY

    with TemporaryDirectory() as directory:
        result = _compiled_application(
            graph, FakeChineseStageLLM(), Path(directory)
        ).run(
            ResearchRequest(
                question=question,
                max_papers=3,
                export_format=ExportFormat.MARKDOWN,
            )
        )

    assert isinstance(result.report, SurveyReport)
    assert result.report.report_mode is ReportMode.FULL_SURVEY


def test_compiled_graph_total_retrieval_failure_does_not_render_survey():
    """Source failures with no papers preserve legacy execution failure semantics."""

    graph = _compiled_graph(papers=[], source_errors={"fixture": "unavailable"})
    with TemporaryDirectory() as directory:
        app = _compiled_application(graph, FakeChineseStageLLM(), Path(directory))
        with pytest.raises(ResearchExecutionError):
            app.run(
                ResearchRequest(
                    question="目标检测与视觉SLAM融合研究进展",
                    max_papers=3,
                    export_format=ExportFormat.MARKDOWN,
                )
            )


@pytest.mark.parametrize("fatal_error", [False, True])
def test_failed_or_fatal_survey_state_never_skips_legacy_failure(fatal_error):
    """A report mode never masks a node failure or nonrecoverable state error."""

    state = _completed_state(ReportMode.EVIDENCE_LIMITED_REVIEW)
    state["next_action"] = NextAction.ABORT
    if fatal_error:
        state["errors"] = [
            ResearchError(
                stage=ResearchStep.RETRIEVAL,
                error_type="FatalFixtureError",
                message="fixture failure",
                recoverable=False,
                attempt=0,
            )
        ]
    else:
        state["current_step"] = ResearchStep.FAILED

    class _SurveyMustNotRun:
        def generate(self, _state):
            raise AssertionError("failed state must not enter survey handoff")

    with TemporaryDirectory() as directory:
        app = ResearchApplicationService(
            _Graph(state),
            _LegacyMustNotRun(),
            ExportService(Path(directory)),
            InMemoryTaskStore(),
            survey_report_generator=_SurveyMustNotRun(),
        )
        with pytest.raises(ResearchExecutionError):
            app.run(
                ResearchRequest(
                    question=state["question"],
                    max_papers=3,
                    export_format=ExportFormat.MARKDOWN,
                )
            )
