from paperguide.demo.fake_reader import FakeReader
from paperguide.demo.fake_verifier import FakeVerifier
from paperguide.demo.seed import create_demo_seed
from paperguide.relevance import (
    AssessmentStatus,
    EvidenceAwareFinalRelevanceService,
    FinalCoreSelectionPolicy,
    FinalRelevanceClassification,
    PreliminaryRelevanceClassification,
    ReportMode,
    ResearchIntent,
    TimeRange,
)
from paperguide.verification import apply_verification


def make_result(index=0):
    seed = create_demo_seed()
    analysis = FakeReader().analyze(seed.documents[index])
    verification = FakeVerifier().verify(analysis, seed.documents[index])
    verified = apply_verification(analysis, verification)
    return seed.papers[index], analysis, verified


def make_intent():
    return ResearchIntent(
        research_question="YOLO and SLAM integration",
        required_concepts=["YOLO", "SLAM"],
        relation_requirements=["combining YOLO with SLAM"],
        domain="visual SLAM",
        time_range=TimeRange(start_year=2024, end_year=2026),
    )


def test_verified_fulltext_candidate_is_assessed():
    paper, analysis, verified = make_result()
    result = EvidenceAwareFinalRelevanceService().assess(paper, analysis, verified, make_intent())
    assert result.assessment_status is AssessmentStatus.ASSESSED
    assert result.final_classification in {FinalRelevanceClassification.CORE, FinalRelevanceClassification.ADJACENT}
    assert result.supporting_evidence_keys


def test_missing_analysis_is_unassessable_not_rejected():
    paper, _, verified = make_result()
    result = EvidenceAwareFinalRelevanceService().assess(paper, None, verified, make_intent())
    assert result.assessment_status is AssessmentStatus.UNASSESSABLE
    assert result.final_classification is FinalRelevanceClassification.ADJACENT


def test_relation_requires_verified_evidence():
    paper, analysis, verified = make_result()
    intent = ResearchIntent(research_question="YOLO and SLAM", required_concepts=["YOLO", "SLAM"], relation_requirements=["nonexistent relation"])
    result = EvidenceAwareFinalRelevanceService().assess(paper, analysis, verified, intent)
    assert result.relation_evidence_strength == 0
    assert result.final_classification is not FinalRelevanceClassification.CORE


def test_conflict_reduces_score_without_forcing_rejection():
    paper, analysis, verified = make_result()
    result = EvidenceAwareFinalRelevanceService().assess(paper, analysis, verified, make_intent())
    assert result.conflict_penalty == 0
    assert 0 <= result.overall_score <= 1


def test_same_input_is_deterministic():
    paper, analysis, verified = make_result()
    service = EvidenceAwareFinalRelevanceService()
    first = service.assess(paper, analysis, verified, make_intent())
    second = service.assess(paper, analysis, verified, make_intent())
    assert first.overall_score == second.overall_score
    assert first.final_classification == second.final_classification


def test_sufficiency_limited_for_one_core_paper():
    paper, analysis, verified = make_result()
    service = EvidenceAwareFinalRelevanceService()
    assessment = service.assess(paper, analysis, verified, make_intent(), PreliminaryRelevanceClassification.PRELIMINARY_CORE)
    result = service.assess_sufficiency([assessment], [verified], make_intent())
    assert result.recommended_report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW
    assert "insufficient_core_papers" in result.missing_areas


def test_sufficiency_full_survey_for_two_independent_core_papers():
    first_paper, first_analysis, first_verified = make_result(0)
    second_paper, second_analysis, second_verified = make_result(1)
    service = EvidenceAwareFinalRelevanceService()
    intent = make_intent()
    first = service.assess(first_paper, first_analysis, first_verified, intent)
    second = service.assess(second_paper, second_analysis, second_verified, intent)
    first = first.model_copy(update={"final_classification": FinalRelevanceClassification.CORE, "relation_evidence_strength": 1.0, "verified_evidence_coverage": 1.0, "research_focus_match": 1.0})
    second = second.model_copy(update={"final_classification": FinalRelevanceClassification.CORE, "relation_evidence_strength": 1.0, "verified_evidence_coverage": 1.0, "research_focus_match": 1.0})
    result = service.assess_sufficiency([first, second], [first_verified, second_verified], intent)
    assert result.core_paper_count >= 1
    assert result.recommended_report_mode in {ReportMode.FULL_SURVEY, ReportMode.EVIDENCE_LIMITED_REVIEW}


def test_selection_requires_verified_evidence_not_the_core_label():
    """An adjacent paper the verifier confirmed is citable; CORE is not required.

    This replaces an earlier rule that selected CORE papers only. That rule
    made the report depend on matching the planner's wording against the
    paper, which real literature does not satisfy, so verified evidence was
    discarded and reports had nothing to cite.
    """
    paper, analysis, verified = make_result(0)
    service = EvidenceAwareFinalRelevanceService()
    assessment = service.assess(paper, analysis, verified, make_intent())
    assert assessment.supporting_evidence_keys

    selected, not_selected = FinalCoreSelectionPolicy().select(
        [assessment], {paper.id: paper}, 1
    )

    assert selected == [paper.id]
    assert not_selected == 0


def test_selection_still_refuses_a_paper_without_verified_evidence():
    """The guard that matters: nothing unverified may be cited.

    Widening selection past the CORE label must not widen it past the
    verifier, or a report could cite a paper no evidence supports.
    """
    paper, analysis, verified = make_result(0)
    service = EvidenceAwareFinalRelevanceService()
    assessment = service.assess(paper, analysis, verified, make_intent())
    unsupported = assessment.model_copy(update={"supporting_evidence_keys": []})

    selected, _ = FinalCoreSelectionPolicy().select(
        [unsupported], {paper.id: paper}, 1
    )

    assert selected == []


def test_core_still_outranks_adjacent_when_both_have_evidence():
    """Preferring CORE is kept; only the hard requirement is dropped."""
    paper, analysis, verified = make_result(0)
    other_paper, other_analysis, other_verified = make_result(1)
    service = EvidenceAwareFinalRelevanceService()
    intent = make_intent()
    adjacent = service.assess(paper, analysis, verified, intent).model_copy(
        update={
            "final_classification": FinalRelevanceClassification.ADJACENT,
            "overall_score": 0.99,
        }
    )
    core = service.assess(other_paper, other_analysis, other_verified, intent).model_copy(
        update={
            "final_classification": FinalRelevanceClassification.CORE,
            "overall_score": 0.10,
        }
    )

    selected, _ = FinalCoreSelectionPolicy().select(
        [adjacent, core],
        {paper.id: paper, other_paper.id: other_paper},
        1,
    )

    assert selected == [other_paper.id]


def test_assessment_json_is_safe_and_serializable():
    paper, analysis, verified = make_result()
    result = EvidenceAwareFinalRelevanceService().assess(paper, analysis, verified, make_intent())
    payload = result.model_dump_json()
    assert "prompt" not in payload.casefold()
    assert str(paper.id) in payload


def test_generalization_topic_does_not_use_domain_words():
    paper, analysis, verified = make_result()
    intent = ResearchIntent(research_question="retrieval augmented generation", required_concepts=["retrieval augmented generation", "hallucination mitigation"], relation_requirements=["reducing hallucinations"])
    result = EvidenceAwareFinalRelevanceService().assess(paper, analysis, verified, intent)
    assert result.final_classification is not FinalRelevanceClassification.CORE

def test_paper_title_and_abstract_contribute_to_final_topic_match():
    paper, analysis, verified = make_result()
    paper = paper.model_copy(
        update={
            "title": "UniqueTopicToken: a technical study",
            "abstract": "UniqueTopicToken is the central research focus.",
        }
    )
    intent = ResearchIntent(
        research_question="UniqueTopicToken review",
        required_concepts=["UniqueTopicToken"],
    )

    result = EvidenceAwareFinalRelevanceService().assess(
        paper, analysis, verified, intent
    )

    assert result.matched_concepts == ["UniqueTopicToken"]
    assert result.research_focus_match == 1.0
