from uuid import uuid4

from paperguide.analysis import EvidenceLinkingService, StatementKind, StatementSupportStatus
from paperguide.demo import FakeReader, FakeVerifier, create_demo_seed
from paperguide.reporting import (
    CitationRegistry,
    CorePaperProfile,
    EvidenceLedgerEntry,
    FishboneReadinessAssessment,
    SurveyEvidenceDataBuilder,
    citation_group,
    citation_token,
)
from paperguide.relevance import (
    EvidenceAwareFinalRelevanceService,
    FinalRelevanceClassification,
    ResearchIntent,
)
from paperguide.verification import apply_verification


def demo_data():
    seed = create_demo_seed()
    linked, verified = {}, {}
    for index, paper in enumerate(seed.papers):
        analysis = FakeReader().analyze(seed.documents[index])
        result = apply_verification(analysis, FakeVerifier().verify(analysis, seed.documents[index]))
        linked[str(paper.id)] = EvidenceLinkingService().link(analysis, result, paper)
        verified[str(paper.id)] = result
    return seed, linked, verified


def test_registry_numbers_start_at_one_and_are_deterministic():
    seed, _, _ = demo_data()
    first = CitationRegistry().build(seed.papers)
    second = CitationRegistry().build(list(reversed(seed.papers)))
    assert [item.citation_number for item in first] == [1, 2, 3]
    assert [item.canonical_identifier for item in first] == [item.canonical_identifier for item in second]


def test_registry_sorts_year_author_title_and_identifier():
    seed, _, _ = demo_data()
    ordered = CitationRegistry().build(seed.papers)
    assert [item.publication_year for item in ordered] == [2024, 2025, 2026]


def test_registry_deduplicates_canonical_papers():
    seed, _, _ = demo_data()
    entries = CitationRegistry().build([seed.papers[0], seed.papers[0].model_copy(update={"id": uuid4()})])
    assert len(entries) == 1


def test_registry_can_restrict_to_selected_core_papers():
    seed, linked, verified = demo_data()
    intent = ResearchIntent(research_question="demo", required_concepts=["demo"])
    assessment = EvidenceAwareFinalRelevanceService().assess(
        seed.papers[0], FakeReader().analyze(seed.documents[0]), verified[str(seed.papers[0].id)], intent
    ).model_copy(update={"final_classification": FinalRelevanceClassification.CORE, "selected_for_report": True})
    entries = CitationRegistry().build(seed.papers, {seed.papers[0].id: assessment})
    assert len(entries) == 1
    assert entries[0].paper_id == seed.papers[0].id


def test_reference_contains_only_real_metadata():
    seed, linked, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    reference = data.references[0]
    assert reference.title
    assert reference.year in {2024, 2025, 2026}
    assert "Unknown Conference" not in reference.model_dump_json()


def test_reference_missing_metadata_is_none_not_invented():
    seed, linked, verified = demo_data()
    paper = seed.papers[0].model_copy(update={"venue": None, "doi": None, "arxiv_id": None})
    data = SurveyEvidenceDataBuilder().build([paper], None, linked, verified)
    assert data.references[0].venue is None
    assert data.references[0].doi is None


def test_citation_tokens_use_locator_page_only_when_present():
    seed, _, _ = demo_data()
    locator = seed.documents[0].pages[0]
    assert citation_token(3) == "[3]"
    assert citation_group([5, 3, 3, 2]) == "[2,3,5]"


def test_ledger_contains_supported_evidence_and_not_unmapped_limitation():
    seed, linked, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    assert data.evidence_ledger
    assert all(item.support_status is not StatementSupportStatus.UNMAPPED for item in data.evidence_ledger)
    assert all(item.evidence_key_internal for item in data.evidence_ledger)


def test_ledger_keeps_conflict_status_and_statement_kind():
    seed, linked, verified = demo_data()
    statement = linked[str(seed.papers[0].id)].contributions[0]
    assert statement.kind is StatementKind.CONTRIBUTION
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    assert all(item.statement_kind in set(StatementKind) for item in data.evidence_ledger)


def test_public_data_does_not_expose_uuid_fields():
    seed, linked, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    public = data.public_dict()
    payload = str(public)
    assert "paper_id" not in payload
    assert "evidence_key_internal" not in payload


def test_internal_json_roundtrip_keeps_traceability():
    seed, linked, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    restored = type(data).model_validate_json(data.model_dump_json())
    assert restored == data
    assert restored.evidence_ledger[0].evidence_key_internal


def test_profiles_are_generated_for_selected_input_papers():
    seed, linked, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    assert len(data.core_paper_profiles) == 3
    assert all(isinstance(item, CorePaperProfile) for item in data.core_paper_profiles)
    assert all(item.primary_contribution is not None for item in data.core_paper_profiles)


def test_unverified_limitation_is_not_promoted_to_primary():
    seed, linked, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    assert all(item.primary_limitation is None for item in data.core_paper_profiles)
    assert all(item.limitation_availability == "NO_VERIFIED_LIMITATION" for item in data.core_paper_profiles)


def test_timeline_contains_selected_papers_in_year_order():
    seed, linked, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    assert [item.year for item in data.literature_timeline] == [2024, 2025, 2026]
    assert all(item.primary_contribution for item in data.literature_timeline)


def test_timeline_missing_limitation_is_explicit():
    seed, linked, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    assert all(item.limitation_status is StatementSupportStatus.UNMAPPED for item in data.literature_timeline)


def test_fishbone_readiness_is_quality_only_and_does_not_fail_data_build():
    seed, linked, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    assert isinstance(data.fishbone_readiness, FishboneReadinessAssessment)
    assert data.fishbone_readiness.total_core_entries == 3
    assert data.fishbone_readiness.ready
    assert data.fishbone_readiness.entries_missing_limitation == 3


def test_build_from_state_uses_optional_linked_field():
    seed, linked, verified = demo_data()
    state = {
        "papers": seed.papers,
        "final_relevance": {},
        "evidence_linked_analysis": linked,
        "verified_results": verified,
    }
    data = SurveyEvidenceDataBuilder().build_from_state(state)  # type: ignore[arg-type]
    assert len(data.citation_registry) == 3


def test_empty_linked_analysis_is_warning_not_fake_evidence():
    seed, _, verified = demo_data()
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, {}, verified)
    assert "MISSING_LINKED_ANALYSIS" in data.warnings
    assert not data.evidence_ledger


def test_citation_entry_does_not_use_internal_uuid_for_sorting():
    seed, _, _ = demo_data()
    first = CitationRegistry().build(seed.papers)
    altered = [paper.model_copy(update={"id": uuid4()}) for paper in seed.papers]
    second = CitationRegistry().build(altered)
    assert [item.citation_number for item in first] == [item.citation_number for item in second]


def test_models_reject_unknown_fields():
    try:
        CorePaperProfile.model_validate({"citation_number": 1, "title": "x", "authors": [], "year": None, "method_summary": "x", "research_problem": "x", "additional_contributions": [], "additional_limitations": [], "key_findings": [], "verified_evidence_count": 0, "grounded_statement_count": 0, "evidence_confidence_summary": 0, "limitation_availability": "NO_VERIFIED_LIMITATION", "unknown": 1})
    except Exception:
        pass
    else:
        raise AssertionError("unknown profile field was accepted")
