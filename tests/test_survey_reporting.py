import re

import pytest
from paperguide.analysis import EvidenceLinkingService
from paperguide.demo import FakeReader, FakeVerifier, create_demo_seed
from paperguide.relevance import ReportMode
from paperguide.reporting import (
    CitationSafeSurveyWriter,
    ClaimCertainty,
    LiteratureMethodFacts,
    ReportSchemaValidationError,
    SurveyClaimDraft,
    SurveyClaimType,
    SurveyContextBudget,
    SurveyEvidenceDataBuilder,
    SurveyNarrativeDraft,
    SurveyReportAssembler,
    SurveyReportContextBuilder,
    SurveyReportVerifier,
)
from paperguide.verification import apply_verification

from tests.production_fixtures import production_provenance


def make_data():
    seed = create_demo_seed()
    papers = production_provenance(seed.papers)
    linked, verified = {}, {}
    for index, paper in enumerate(papers):
        analysis = FakeReader().analyze(seed.documents[index])
        result = apply_verification(analysis, FakeVerifier().verify(analysis, seed.documents[index]))
        linked[str(paper.id)] = EvidenceLinkingService().link(analysis, result, paper)
        verified[str(paper.id)] = result
    return seed, SurveyEvidenceDataBuilder().build(papers, None, linked, verified)


def make_context(mode=ReportMode.FULL_SURVEY, budget=None):
    _, data = make_data()
    return SurveyReportContextBuilder(budget).build("demo research question", data, mode, LiteratureMethodFacts())


def test_core_papers_and_grounded_statements_enter_context():
    context = make_context()
    assert len(context.core_papers) == 3
    assert context.grounded_statements
    assert context.allowed_statement_keys


def test_context_is_public_and_contains_no_uuid_fields():
    context = make_context()
    payload = context.public_dict()
    text = str(payload)
    assert "paper_id" not in text
    assert "evidence_id" not in text
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)


def test_unmapped_limitation_is_not_grounded_context():
    context = make_context()
    assert all(item.is_evidence_grounded for item in context.grounded_statements)
    assert all(item.statement_kind.value != "limitation" for item in context.grounded_statements)


def test_conflicted_statements_are_separate():
    context = make_context()
    assert isinstance(context.conflicted_statements, list)


def test_context_budget_is_deterministic_and_warns():
    context = make_context(budget=SurveyContextBudget(max_core_papers=1, max_context_characters=2_000))
    assert context.truncated
    assert "SURVEY_CONTEXT_TRUNCATED" in context.warnings


def test_literature_facts_missing_audit_are_zero():
    facts = LiteratureMethodFacts.from_state({"analyses": {}})  # type: ignore[arg-type]
    assert facts.planned_queries == 0
    assert facts.papers_read == 0


class FakeSurveyLLM:
    def __init__(self, unknown=False):
        self.unknown = unknown
        self.calls = 0

    def generate_structured(self, *, system_prompt, user_prompt, response_model):
        self.calls += 1
        key = "unknown-key" if self.unknown else user_prompt.split("Allowed statement keys: [", 1)[1].split("]", 1)[0].strip('"').split('"')[0]
        return SurveyNarrativeDraft(
            title="Evidence-grounded survey",
            abstract="A bounded summary.",
            introduction="The scope is bounded by selected papers.",
            literature_method_summary="The retrieval audit was used.",
            evidence_summary="Verified findings are reported.",
            limitations="Evidence coverage remains bounded.",
            conclusion="The evidence supports a cautious conclusion.",
            claims=[SurveyClaimDraft(text="A verified finding.", source_statement_keys=[key], claim_type=SurveyClaimType.FINDING, certainty=ClaimCertainty.MEDIUM)],
        )


def test_writer_returns_narrative_draft_not_final_references():
    context = make_context()
    llm = FakeSurveyLLM()
    draft = CitationSafeSurveyWriter(llm).write(context)
    assert draft.title
    assert llm.calls == 1


def test_writer_rejects_unknown_statement_key():
    context = make_context()
    with pytest.raises(Exception, match="UNKNOWN_REPORT_STATEMENT_KEY"):
        CitationSafeSurveyWriter(FakeSurveyLLM(unknown=True)).write(context)


def test_writer_does_not_accept_uuid_as_statement_key():
    context = make_context()
    fake = FakeSurveyLLM()
    fake.unknown = True
    with pytest.raises(ReportSchemaValidationError, match="UNKNOWN_REPORT_STATEMENT_KEY"):
        CitationSafeSurveyWriter(fake).write(context)


def test_assembler_reconstructs_citations_from_statement_keys():
    context = make_context()
    llm = FakeSurveyLLM()
    draft = CitationSafeSurveyWriter(llm).write(context)
    _, data = make_data()
    report = SurveyReportAssembler().assemble(draft, data, ReportMode.FULL_SURVEY)
    assert report.claims[0].citation_tokens
    assert report.references
    assert report.evidence_appendix


def test_assembler_rejects_unsourced_factual_claim():
    _, data = make_data()
    draft = SurveyNarrativeDraft(
        title="x", abstract="x", introduction="x", literature_method_summary="x", evidence_summary="x", limitations="x", conclusion="x",
        claims=[SurveyClaimDraft(text="unsupported", source_statement_keys=[], claim_type=SurveyClaimType.FINDING)],
    )
    with pytest.raises(Exception, match="UNSUPPORTED_SURVEY_CLAIM"):
        SurveyReportAssembler().assemble(draft, data, ReportMode.FULL_SURVEY)


def test_assembler_allows_unsourced_background_transition():
    _, data = make_data()
    draft = SurveyNarrativeDraft(
        title="x", abstract="x", introduction="x", literature_method_summary="x", evidence_summary="x", limitations="x", conclusion="x",
        claims=[SurveyClaimDraft(text="background", source_statement_keys=[], claim_type=SurveyClaimType.BACKGROUND)],
    )
    report = SurveyReportAssembler().assemble(draft, data, ReportMode.FULL_SURVEY)
    assert report.claims[0].citation_tokens == []


def test_limited_mode_adds_conservative_warning():
    context = make_context(ReportMode.EVIDENCE_LIMITED_REVIEW)
    draft = CitationSafeSurveyWriter(FakeSurveyLLM()).write(context)
    _, data = make_data()
    report = SurveyReportAssembler().assemble(draft, data, ReportMode.EVIDENCE_LIMITED_REVIEW)
    assert any("EVIDENCE_LIMITED_REVIEW" in warning for warning in report.warnings)


def test_report_public_view_hides_internal_ids_and_statement_keys():
    context = make_context()
    draft = CitationSafeSurveyWriter(FakeSurveyLLM()).write(context)
    _, data = make_data()
    report = SurveyReportAssembler().assemble(draft, data, ReportMode.FULL_SURVEY)
    payload = str(report.public_dict())
    assert "source_statement_keys" not in payload
    assert "evidence_key_internal" not in payload
    assert "paper_id" not in payload


def test_same_input_produces_same_assembled_report():
    context = make_context()
    draft = CitationSafeSurveyWriter(FakeSurveyLLM()).write(context)
    _, data = make_data()
    first = SurveyReportAssembler().assemble(draft, data, ReportMode.FULL_SURVEY)
    second = SurveyReportAssembler().assemble(draft, data, ReportMode.FULL_SURVEY)
    assert first == second


def test_report_verifier_accepts_reconstructed_claim_bindings():
    context = make_context()
    draft = CitationSafeSurveyWriter(FakeSurveyLLM()).write(context)
    _, data = make_data()
    report = SurveyReportAssembler().assemble(draft, data, ReportMode.FULL_SURVEY)
    assert SurveyReportVerifier().verify(report, context) == report


def test_report_verifier_rejects_missing_claim_citation():
    context = make_context()
    draft = CitationSafeSurveyWriter(FakeSurveyLLM()).write(context)
    _, data = make_data()
    report = SurveyReportAssembler().assemble(draft, data, ReportMode.FULL_SURVEY)
    changed = report.model_copy(update={"claims": [report.claims[0].model_copy(update={"citation_tokens": []})] + report.claims[1:]})
    with pytest.raises(Exception, match="MISSING_CITATION_TOKEN"):
        SurveyReportVerifier().verify(changed, context)


def test_report_verifier_rejects_uuid_in_public_narrative():
    context = make_context()
    draft = CitationSafeSurveyWriter(FakeSurveyLLM()).write(context)
    _, data = make_data()
    report = SurveyReportAssembler().assemble(draft, data, ReportMode.FULL_SURVEY)
    changed = report.model_copy(update={"abstract": "leaked 550e8400-e29b-41d4-a716-446655440000"})
    with pytest.raises(Exception, match="PUBLIC_INTERNAL_ID_LEAK"):
        SurveyReportVerifier().verify(changed, context)
