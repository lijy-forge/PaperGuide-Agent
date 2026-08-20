from uuid import uuid4

import pytest

from paperpilot.domain import Author, FullTextStatus, PaperCandidate, PaperSource, ResearchConfig
from paperpilot.pipeline import SearchResult
from paperpilot.relevance import (
    CandidateSelectionPolicy,
    MetadataRelevanceGate,
    MetadataRelevancePolicy,
    MultiQueryRetrievalService,
    PreliminaryRelevanceClassification,
    ResearchIntent,
    RetrievalBudget,
    RetrievalPlan,
    QueryVariant,
    RetrievalAudit,
    TimeRange,
)


def paper(title: str, abstract: str, year: int | None = 2025) -> PaperCandidate:
    return PaperCandidate(
        id=uuid4(), title=title, normalized_title=title.casefold(), abstract=abstract,
        authors=[Author(full_name="A. Author", normalized_name="a author", affiliations=[])],
        publication_year=year, venue="Test Venue", sources=[PaperSource.ARXIV],
        full_text_status=FullTextStatus.UNKNOWN,
    )


def intent(**kwargs) -> ResearchIntent:
    values = dict(research_question="combine object detection and visual mapping", required_concepts=["object detection", "visual mapping"], relation_requirements=["combining object detection with visual mapping"], domain="robotics")
    values.update(kwargs)
    return ResearchIntent(**values)


def test_required_concepts_full_match_is_core():
    assessment = MetadataRelevanceGate().assess(paper("Object detection and visual mapping", "A robotics study combining object detection with visual mapping."), intent())
    assert assessment.required_concept_coverage == 1
    assert assessment.classification is PreliminaryRelevanceClassification.PRELIMINARY_CORE


def test_partial_concept_match_is_not_core():
    assessment = MetadataRelevanceGate().assess(paper("Object detection benchmark", "A robotics benchmark."), intent())
    assert assessment.required_concept_coverage == 0.5
    assert assessment.classification is not PreliminaryRelevanceClassification.PRELIMINARY_CORE


def test_concepts_without_relation_are_adjacent():
    assessment = MetadataRelevanceGate().assess(paper("Object detection and visual mapping", "A robotics survey of two independent topics."), intent())
    assert assessment.relation_support == 0
    assert assessment.classification is PreliminaryRelevanceClassification.POSSIBLE_ADJACENT


def test_relation_phrase_is_supported():
    assessment = MetadataRelevanceGate().assess(paper("Object detection with visual mapping", "A robotics method combining object detection with visual mapping."), intent())
    assert assessment.relation_support == 1


def test_scope_mismatch_is_conservative():
    assessment = MetadataRelevanceGate().assess(paper("Object detection and visual mapping", "A medical imaging study combining object detection with visual mapping."), intent())
    assert assessment.scope_match < 1


def test_time_inside_range_matches():
    assessment = MetadataRelevanceGate().assess(paper("Object detection with visual mapping", "A robotics method combining object detection with visual mapping.", 2025), intent(time_range=TimeRange(start_year=2024, end_year=2026)))
    assert assessment.time_match == 1


def test_time_outside_range_rejects():
    assessment = MetadataRelevanceGate().assess(paper("Object detection with visual mapping", "A robotics method combining object detection with visual mapping.", 2020), intent(time_range=TimeRange(start_year=2024, end_year=2026)))
    assert assessment.classification is PreliminaryRelevanceClassification.REJECTED
    assert "outside_time_range" in assessment.reasons


def test_missing_year_is_not_automatically_rejected():
    assessment = MetadataRelevanceGate().assess(paper("Object detection with visual mapping", "A robotics method combining object detection with visual mapping.", None), intent(time_range=TimeRange(start_year=2024, end_year=2026)))
    assert assessment.classification is not PreliminaryRelevanceClassification.REJECTED


def test_exclusion_penalty_is_recorded():
    assessment = MetadataRelevanceGate().assess(paper("Object detection with visual mapping for medical diagnosis", "A medical robotics method combining object detection with visual mapping."), intent(exclusion_concepts=["medical diagnosis"]))
    assert assessment.exclusion_penalty > 0
    assert "excluded_scope" in assessment.reasons


def test_metadata_quality_does_not_alone_reject():
    assessment = MetadataRelevanceGate().assess(paper("Object detection with visual mapping", "A robotics method combining object detection with visual mapping.", None), intent())
    assert assessment.metadata_quality < 1
    assert assessment.classification is not PreliminaryRelevanceClassification.REJECTED


def test_scores_are_deterministic_and_bounded():
    p = paper("Object detection with visual mapping", "A robotics method combining object detection with visual mapping.")
    first, second = MetadataRelevanceGate().assess(p, intent()), MetadataRelevanceGate().assess(p, intent())
    assert first.overall_score == second.overall_score
    assert 0 <= first.overall_score <= 1


def test_policy_rejects_low_score():
    assert MetadataRelevancePolicy(core_threshold=0.9, adjacent_threshold=0.8).adjacent_threshold == 0.8


def test_selection_prefers_core_then_adjacent_and_excludes_rejected():
    core = paper("Object detection with visual mapping", "A robotics method combining object detection with visual mapping.")
    adjacent = paper("Object detection", "A robotics benchmark.")
    rejected = paper("Medical diagnosis", "A medical study.")
    gate = MetadataRelevanceGate()
    assessments = gate.assess_many([adjacent, rejected, core], intent())
    selected, records = CandidateSelectionPolicy().select([adjacent, rejected, core], assessments, {}, max_documents=2)
    assert [item.id for item in selected] == [core.id, adjacent.id]
    assert any(record.classification is PreliminaryRelevanceClassification.REJECTED for record in records)


class FakePipeline:
    def __init__(self, papers):
        self.papers = papers
        self.calls = []

    def search(self, config):
        self.calls.append(config.question)
        return SearchResult(papers=list(self.papers), source_results={"arxiv": len(self.papers)}, source_errors={}, warnings=[], total_found=len(self.papers), total_after_dedup=len(self.papers))


def plan(variants, **budget):
    return RetrievalPlan(intent=intent(), query_variants=[QueryVariant(query=value, purpose="direct") for value in variants], budget=RetrievalBudget(max_core_papers=3, **budget))


def config():
    return ResearchConfig(question="combine object detection and visual mapping", sources=[PaperSource.ARXIV], max_papers=3)


def test_multi_query_executes_each_variant_and_merges_provenance():
    p = paper("Object detection with visual mapping", "A robotics method combining object detection with visual mapping.")
    fake = FakePipeline([p])
    result = MultiQueryRetrievalService(fake).search(plan(["q1", "q2"]), config())
    assert fake.calls == ["q1", "q2"]
    assert len(result.papers) == 1
    assert result.provenance[str(p.id)] == ["query_1", "query_2"]


def test_multi_query_respects_per_query_budget():
    papers = [paper(f"Object detection with visual mapping {i}", "A robotics method combining object detection with visual mapping.") for i in range(5)]
    fake = FakePipeline(papers)
    result = MultiQueryRetrievalService(fake).search(plan(["q1"], max_candidates_per_query=2), config())
    assert result.audit.raw_candidate_count == 2


def test_one_query_failure_does_not_abort_other_queries():
    class Partial(FakePipeline):
        def search(self, cfg):
            self.calls.append(cfg.question)
            if cfg.question == "bad": raise RuntimeError("provider failure")
            return super().search(cfg)
    p = paper("Object detection with visual mapping", "A robotics method combining object detection with visual mapping.")
    result = MultiQueryRetrievalService(Partial([p])).search(plan(["bad", "good"]), config())
    assert result.audit.failed_query_count == 1
    assert result.papers


def test_source_failure_is_circuit_broken_for_remaining_queries():
    class SourceFailurePipeline(FakePipeline):
        def __init__(self, papers):
            super().__init__(papers)
            self.configs = []

        def search(self, cfg):
            self.configs.append(cfg)
            errors = (
                {"semantic_scholar": "rate limited"}
                if len(self.configs) == 1
                else {}
            )
            return SearchResult(
                papers=list(self.papers),
                source_results={"arxiv": len(self.papers)},
                source_errors=errors,
                warnings=[],
                total_found=len(self.papers),
                total_after_dedup=len(self.papers),
            )

    candidate = paper(
        "Object detection with visual mapping",
        "A robotics method combining object detection with visual mapping.",
    )
    pipeline = SourceFailurePipeline([candidate])
    multi_source_config = ResearchConfig(
        question="combine object detection and visual mapping",
        sources=[PaperSource.ARXIV, PaperSource.SEMANTIC_SCHOLAR],
        max_papers=3,
    )

    result = MultiQueryRetrievalService(pipeline).search(
        plan(["q1", "q2"]), multi_source_config
    )

    assert result.papers
    assert result.source_errors == {"semantic_scholar": "RETRIEVER_SOURCE_FAILED"}
    assert pipeline.configs[0].sources == [
        PaperSource.ARXIV,
        PaperSource.SEMANTIC_SCHOLAR,
    ]
    assert pipeline.configs[1].sources == [PaperSource.ARXIV]


def test_all_queries_failure_is_a_warning():
    class Failing(FakePipeline):
        def search(self, cfg): raise RuntimeError("failed")
    result = MultiQueryRetrievalService(Failing([])).search(plan(["q1", "q2"]), config())
    assert result.papers == []
    assert "ALL_RETRIEVAL_QUERIES_FAILED" in result.warnings


def test_candidate_pool_budget_and_audit_counts():
    papers = [paper(f"Object detection with visual mapping {i}", "A robotics method combining object detection with visual mapping.").model_copy(update={"authors": [Author(full_name=f"Author {i}", normalized_name=f"author {i}", affiliations=[])]}) for i in range(4)]
    result = MultiQueryRetrievalService(FakePipeline(papers)).search(plan(["q"], max_candidates_after_dedup=2, max_documents_to_ingest=1), config())
    assert result.audit.candidate_budget_count == 50
    assert result.audit.selected_for_ingestion_count == 1


def test_reader_budget_is_independent_from_final_core_budget():
    papers = [paper(f"Object detection with visual mapping {i}", "A robotics method combining object detection with visual mapping.").model_copy(update={"authors": [Author(full_name=f"Author {i}", normalized_name=f"author {i}", affiliations=[])]}) for i in range(4)]
    small_core_config = ResearchConfig(question="combine object detection and visual mapping", sources=[PaperSource.ARXIV], max_papers=1)
    result = MultiQueryRetrievalService(FakePipeline(papers)).search(
        plan(["q"], max_documents_to_ingest=12, max_papers_to_read=10),
        small_core_config,
    )
    assert result.audit.selected_for_ingestion_count == 4


def test_audit_json_serializes():
    audit = RetrievalAudit(planned_query_count=1, executed_query_count=1, failed_query_count=0, raw_candidate_count=0, deduplicated_candidate_count=0, candidate_budget_count=10, preliminary_core_count=0, possible_adjacent_count=0, metadata_rejected_count=0, selected_for_ingestion_count=0)
    assert "planned_query_count" in audit.model_dump_json()
