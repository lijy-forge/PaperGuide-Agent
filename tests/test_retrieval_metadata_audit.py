"""Targeted tests for private retrieval/metadata auditability."""

from pathlib import Path
from uuid import uuid4

import pytest
from paperguide.application import ResearchTaskStatus
from paperguide.domain import Author, FullTextStatus, PaperCandidate, PaperSource, ResearchConfig
from paperguide.orchestration import create_initial_state
from paperguide.orchestration.nodes import RetrieverNode
from paperguide.pipeline import SearchResult
from paperguide.progress.events import TaskEventType
from paperguide.relevance import (
    MetadataRelevanceGate,
    MultiQueryRetrievalService,
    PreliminaryRelevanceClassification,
    QueryVariant,
    ResearchIntent,
    RetrievalBudget,
    RetrievalPlan,
    audit_hash,
    classify_text_language,
    normalize_audit_text,
    stable_paper_identity,
)

from tests.api_fixtures import APITestRuntime


def make_paper(
    title: str,
    abstract: str | None,
    *,
    arxiv_id: str,
    year: int | None = 2025,
) -> PaperCandidate:
    return PaperCandidate(
        id=uuid4(),
        title=title,
        normalized_title=title.casefold(),
        abstract=abstract,
        authors=[Author(full_name="A. Author", affiliations=[])],
        publication_year=year,
        venue="Venue",
        arxiv_id=arxiv_id,
        sources=[PaperSource.ARXIV],
        landing_page_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        full_text_status=FullTextStatus.AVAILABLE,
    )


def make_intent(*, chinese: bool = False) -> ResearchIntent:
    if chinese:
        return ResearchIntent(
            research_question="目标检测与视觉 SLAM 融合",
            required_concepts=["目标检测", "视觉 SLAM"],
            related_concepts=["语义建图"],
            relation_requirements=["目标检测与视觉 SLAM 融合"],
            domain="机器人学",
            query_language="zh",
        )
    return ResearchIntent(
        research_question="object detection with visual SLAM",
        required_concepts=["object detection", "visual SLAM"],
        related_concepts=["semantic mapping"],
        relation_requirements=["object detection with visual SLAM"],
        domain="robotics",
        query_language="en",
    )


def make_plan(queries: list[str], *, chinese: bool = False) -> RetrievalPlan:
    return RetrievalPlan(
        intent=make_intent(chinese=chinese),
        query_variants=[QueryVariant(query=query, purpose="direct") for query in queries],
        budget=RetrievalBudget(max_core_papers=5),
    )


def make_config() -> ResearchConfig:
    return ResearchConfig(
        question="object detection with visual SLAM",
        max_papers=5,
        sources=[PaperSource.ARXIV],
    )


class QueryPipeline:
    def __init__(self, results: dict[str, list[PaperCandidate]]):
        self.results = results

    def search(self, config):
        papers = [paper.model_copy(deep=True) for paper in self.results.get(config.question, [])]
        return SearchResult(
            papers=papers,
            source_results={"arxiv": len(papers)},
            source_errors={},
            warnings=[],
            total_found=len(papers),
            total_after_dedup=len(papers),
        )


def relevant_paper(arxiv_id: str = "2501.00001") -> PaperCandidate:
    return make_paper(
        "Object detection with visual SLAM",
        "A robotics method integrating object detection with visual SLAM for semantic mapping.",
        arxiv_id=arxiv_id,
    )


def test_query_audit_hash_is_stable_and_normalized() -> None:
    assert audit_hash(normalize_audit_text("  Visual   SLAM  ")) == audit_hash("visual slam")
    assert len(audit_hash("query")) == 64


def test_normalized_query_duplicate_detection() -> None:
    service = MultiQueryRetrievalService(QueryPipeline({}))
    _, audit = service.search_with_diagnostics(make_plan(["Visual  SLAM", "visual slam"]), make_config())
    assert audit is not None
    assert audit.exact_unique_query_count == 2
    assert audit.normalized_unique_query_count == 1
    assert audit.queries[1].normalized_duplicate is True


def test_five_identical_query_variants_are_detected() -> None:
    service = MultiQueryRetrievalService(QueryPipeline({}))
    _, audit = service.search_with_diagnostics(make_plan(["same query"] * 5), make_config())
    assert audit is not None
    assert audit.exact_unique_query_count == 1
    assert audit.normalized_unique_query_count == 1
    assert audit.duplicate_query_count == 4


def test_empty_candidate_replay_is_not_claimed_as_determinism_pass() -> None:
    service = MultiQueryRetrievalService(QueryPipeline({}))
    _, audit = service.search_with_diagnostics(make_plan(["q"]), make_config())
    assert audit is not None
    assert audit.metadata_determinism is None


def test_distinct_query_variants_remain_distinct() -> None:
    service = MultiQueryRetrievalService(QueryPipeline({}))
    _, audit = service.search_with_diagnostics(make_plan(["query one", "query two", "query three"]), make_config())
    assert audit is not None
    assert audit.normalized_unique_query_count == 3
    assert audit.duplicate_query_count == 0


def test_per_query_result_identity_uses_public_identifier_hash() -> None:
    paper = relevant_paper()
    service = MultiQueryRetrievalService(QueryPipeline({"q": [paper]}))
    _, audit = service.search_with_diagnostics(make_plan(["q"]), make_config())
    assert audit is not None
    assert audit.queries[0].result_identity_types == ["arxiv_id"]
    assert audit.queries[0].result_identities == [stable_paper_identity(paper)[1]]
    assert str(paper.id) not in audit.model_dump_json()


def test_retrieval_overlap_jaccard_is_exact() -> None:
    first, second = relevant_paper("2501.00001"), relevant_paper("2501.00002")
    pipeline = QueryPipeline({"q1": [first, second], "q2": [first]})
    _, audit = MultiQueryRetrievalService(pipeline).search_with_diagnostics(make_plan(["q1", "q2"]), make_config())
    assert audit is not None
    assert audit.overlaps[0].intersection_count == 1
    assert audit.overlaps[0].union_count == 2
    assert audit.overlaps[0].jaccard == 0.5


def test_dedup_group_audit_records_real_match_strategy() -> None:
    left, right = relevant_paper("2501.00001"), relevant_paper("2501.00001")
    pipeline = QueryPipeline({"q1": [left], "q2": [right]})
    result, audit = MultiQueryRetrievalService(pipeline).search_with_diagnostics(make_plan(["q1", "q2"]), make_config())
    assert audit is not None
    assert len(result.papers) == 1
    assert audit.dedup_groups[0].group_size == 2
    assert "arxiv_id" in audit.dedup_groups[0].matched_by
    assert audit.dedup_groups[0].potentially_incorrect is False


def test_different_papers_have_different_audit_identity() -> None:
    first = relevant_paper("2501.00001")
    second = relevant_paper("2501.00002")
    assert stable_paper_identity(first)[1] != stable_paper_identity(second)[1]


def test_metadata_score_and_components_are_recorded() -> None:
    service = MultiQueryRetrievalService(QueryPipeline({"q": [relevant_paper()]}))
    _, audit = service.search_with_diagnostics(make_plan(["q"]), make_config())
    assert audit is not None
    candidate = audit.candidates[0]
    assert candidate.metadata_score > 0
    assert candidate.required_concept_coverage == 1
    assert candidate.score_arithmetic_consistent is True


def test_metadata_classification_is_recorded() -> None:
    service = MultiQueryRetrievalService(QueryPipeline({"q": [relevant_paper()]}))
    _, audit = service.search_with_diagnostics(make_plan(["q"]), make_config())
    assert audit is not None
    assert audit.candidates[0].classification == PreliminaryRelevanceClassification.PRELIMINARY_CORE.value


def test_threshold_distances_use_existing_policy() -> None:
    service = MultiQueryRetrievalService(QueryPipeline({"q": [relevant_paper()]}))
    _, audit = service.search_with_diagnostics(make_plan(["q"]), make_config())
    assert audit is not None
    candidate = audit.candidates[0]
    policy = MetadataRelevanceGate().policy
    assert candidate.distance_to_adjacent_threshold == pytest.approx(candidate.metadata_score - policy.adjacent_threshold)
    assert candidate.distance_to_core_threshold == pytest.approx(candidate.metadata_score - policy.core_threshold)


def test_missing_abstract_is_recorded_without_content() -> None:
    paper = make_paper("Object detection with visual SLAM", None, arxiv_id="2501.00003")
    _, audit = MultiQueryRetrievalService(QueryPipeline({"q": [paper]})).search_with_diagnostics(make_plan(["q"]), make_config())
    assert audit is not None
    assert audit.candidates[0].abstract_present is False
    assert audit.candidates[0].abstract_char_count == 0
    assert "abstract" not in audit.candidates[0].model_dump()


def test_intent_language_classification() -> None:
    _, audit = MultiQueryRetrievalService(QueryPipeline({})).search_with_diagnostics(make_plan(["目标检测 SLAM"], chinese=True), make_config())
    assert audit is not None
    assert audit.queries[0].language == "MIXED"
    assert audit.intent.language_counts["ZH"] >= 1


def test_candidate_metadata_language_classification() -> None:
    assert classify_text_language("English visual SLAM paper") == "EN"
    assert classify_text_language("视觉定位论文") == "ZH"
    assert classify_text_language("视觉 SLAM") == "MIXED"


def test_metadata_replay_is_deterministic() -> None:
    _, audit = MultiQueryRetrievalService(QueryPipeline({"q": [relevant_paper()]})).search_with_diagnostics(make_plan(["q"]), make_config())
    assert audit is not None
    assert audit.metadata_determinism is True


def test_public_api_excludes_private_audit_events() -> None:
    runtime = APITestRuntime()
    try:
        task = runtime.save_task(ResearchTaskStatus.RUNNING)
        runtime.broker.record_diagnostic_event(
            task.task_id,
            TaskEventType.METADATA_CANDIDATE_AUDIT,
            ResearchTaskStatus.RUNNING,
            {"identity_hash": "a" * 64, "metadata_score": 0.25},
        )
        response = runtime.client.get(f"/api/v1/tasks/{task.task_id}/events")
        assert response.status_code == 200
        assert "metadata_candidate_audit" not in response.text
        assert "identity_hash" not in response.text
        assert "metadata_score" not in response.text
    finally:
        runtime.close()


def test_dashboard_has_no_private_audit_detail() -> None:
    source_root = Path(__file__).parents[1] / "paperguide-dashboard" / "src"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.ts*") if path.is_file())
    for private_field in ("identity_hash", "metadata_score", "normalized_query_hash", "safe_term_preview"):
        assert private_field not in source


def test_diagnostic_publish_failure_does_not_change_retrieval_result() -> None:
    class FailingDiagnosticPublisher:
        def publish(self, *args, **kwargs):
            return None

        def publish_diagnostic(self, *args, **kwargs):
            raise OSError("diagnostic unavailable")

    plan = make_plan(["q"])
    service = MultiQueryRetrievalService(QueryPipeline({"q": [relevant_paper()]}))
    node = RetrieverNode(
        service.pipeline,
        multi_query_service=service,
        progress_publisher=FailingDiagnosticPublisher(),
    )
    state = create_initial_state(make_config().question, make_config())
    state["retrieval_plan"] = plan
    result = node.execute(state)
    assert len(result["papers"]) == 1
    assert result["errors"] == []


def test_audit_path_preserves_business_result() -> None:
    pipeline_one = QueryPipeline({"q": [relevant_paper()]})
    pipeline_two = QueryPipeline({"q": [relevant_paper()]})
    plain = MultiQueryRetrievalService(pipeline_one).search(make_plan(["q"]), make_config())
    audited, diagnostic = MultiQueryRetrievalService(pipeline_two).search_with_diagnostics(make_plan(["q"]), make_config())
    assert diagnostic is not None
    assert [paper.normalized_title for paper in plain.papers] == [paper.normalized_title for paper in audited.papers]
    assert plain.audit.model_dump() == audited.audit.model_dump()
    assert [record.classification for record in plain.records] == [record.classification for record in audited.records]
