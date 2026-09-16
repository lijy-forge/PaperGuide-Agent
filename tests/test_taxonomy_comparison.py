import pytest
from paperguide.analysis import EvidenceLinkingService
from paperguide.demo import FakeReader, FakeVerifier, create_demo_seed
from paperguide.relevance import ReportMode
from paperguide.reporting import (
    ComparisonColumn,
    ComparisonDataBuilder,
    DeterministicTaxonomyBuilder,
    MethodFamilyAssignmentDraft,
    MethodFamilyDraft,
    SurveyEvidenceDataBuilder,
    TaxonomyContextBuilder,
    TaxonomyLLMOutput,
    TaxonomyService,
    TaxonomyValidator,
)
from paperguide.verification import apply_verification


def make_inputs():
    seed = create_demo_seed()
    linked, verified = {}, {}
    for index, paper in enumerate(seed.papers):
        analysis = FakeReader().analyze(seed.documents[index])
        result = apply_verification(analysis, FakeVerifier().verify(analysis, seed.documents[index]))
        linked[str(paper.id)] = EvidenceLinkingService().link(analysis, result, paper)
        verified[str(paper.id)] = result
    data = SurveyEvidenceDataBuilder().build(seed.papers, None, linked, verified)
    return seed, linked, verified, data


def test_taxonomy_context_is_selected_and_compact():
    _, _, _, data = make_inputs()
    context = TaxonomyContextBuilder().build(data)
    assert len(context.papers) == 3
    assert context.allowed_statement_keys
    assert "evidence" not in context.context_text.lower()


def test_taxonomy_key_is_deterministic_and_singletons_allowed():
    _, _, _, data = make_inputs()
    context = TaxonomyContextBuilder().build(data)
    first = DeterministicTaxonomyBuilder().build(context)
    second = DeterministicTaxonomyBuilder().build(context)
    assert [item.family_key for item in first.taxonomy] == [item.family_key for item in second.taxonomy]
    assert all(item.support_level.value in {"single_paper", "multi_paper"} for item in first.taxonomy)


def test_unknown_taxonomy_key_is_rejected():
    _, _, _, data = make_inputs()
    context = TaxonomyContextBuilder().build(data)
    output = TaxonomyLLMOutput(
        families=[MethodFamilyDraft(name="F", description="d", common_mechanism="m", member_citation_numbers=[1], source_statement_keys=["bad"])],
        assignments=[MethodFamilyAssignmentDraft(citation_number=1, primary_family_name="F")],
    )
    with pytest.raises(Exception, match="unknown taxonomy statement key"):
        TaxonomyValidator().validate(output, context)


def test_taxonomy_service_degrades_without_llm_in_limited_mode():
    _, _, _, data = make_inputs()
    context = TaxonomyContextBuilder().build(data)
    result = TaxonomyService().generate(context, ReportMode.EVIDENCE_LIMITED_REVIEW)
    assert not result.available
    assert "TAXONOMY_UNAVAILABLE" in result.warnings


def test_comparison_is_core_only_and_has_no_fabricated_optional_values():
    seed, linked, verified, data = make_inputs()
    taxonomy = DeterministicTaxonomyBuilder().build(TaxonomyContextBuilder().build(data))
    result = ComparisonDataBuilder().build(data, seed.papers, linked, verified, taxonomy)
    assert len(result.comparison_matrix.rows) == 3
    assert ComparisonColumn.PRIMARY_CONTRIBUTION in result.comparison_matrix.columns
    assert result.comparison_facts.papers_without_verified_limitation == 3


def test_comparison_json_public_view_and_facts():
    seed, linked, verified, data = make_inputs()
    taxonomy = DeterministicTaxonomyBuilder().build(TaxonomyContextBuilder().build(data))
    result = ComparisonDataBuilder().build(data, seed.papers, linked, verified, taxonomy)
    payload = result.public_dict()
    assert "comparison_matrix" in payload
    assert "source_statement_keys" not in str(payload)


def test_validator_rejects_non_core_citation_and_duplicate_primary():
    _, _, _, data = make_inputs()
    context = TaxonomyContextBuilder().build(data)
    key = context.allowed_statement_keys[0]
    base = dict(name="F", description="d", common_mechanism="m", member_citation_numbers=[1], source_statement_keys=[key])
    with pytest.raises(Exception, match="unknown or non-core citation"):
        TaxonomyValidator().validate(TaxonomyLLMOutput(families=[MethodFamilyDraft(**{**base, "member_citation_numbers": [99]})], assignments=[]), context)
    with pytest.raises(Exception, match="duplicate primary"):
        TaxonomyValidator().validate(TaxonomyLLMOutput(families=[MethodFamilyDraft(**base)], assignments=[MethodFamilyAssignmentDraft(citation_number=1, primary_family_name="F"), MethodFamilyAssignmentDraft(citation_number=1, primary_family_name="F")]), context)


def test_unclassified_core_is_explicitly_warned():
    _, _, _, data = make_inputs()
    context = TaxonomyContextBuilder().build(data)
    output = TaxonomyLLMOutput(families=[], assignments=[])
    assessment = TaxonomyValidator().validate(output, context)
    assert all(item.primary_method_family == "UNCLASSIFIED" for item in assessment.assignments)
    assert "TAXONOMY_UNCLASSIFIED_CORE" in assessment.warnings


class FakeTaxonomyLLM:
    def __init__(self, key):
        self.key = key
        self.calls = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        return TaxonomyLLMOutput(
            families=[MethodFamilyDraft(name="Shared mechanism", description="bounded", common_mechanism="shared", member_citation_numbers=[1, 2], source_statement_keys=[self.key])],
            assignments=[MethodFamilyAssignmentDraft(citation_number=1, primary_family_name="Shared mechanism"), MethodFamilyAssignmentDraft(citation_number=2, primary_family_name="Shared mechanism")],
            summary="one bounded family",
        )


def test_full_survey_taxonomy_uses_one_structured_call():
    _, _, _, data = make_inputs()
    context = TaxonomyContextBuilder().build(data)
    llm = FakeTaxonomyLLM(context.allowed_statement_keys[0])
    result = TaxonomyService(llm=llm).generate(context, ReportMode.FULL_SURVEY)
    assert result.available and llm.calls == 1
    assert result.taxonomy[0].support_level.value == "multi_paper"
