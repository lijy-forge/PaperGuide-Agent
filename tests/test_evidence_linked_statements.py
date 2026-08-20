from uuid import uuid4

import pytest

from paperpilot.analysis import (
    EvidenceLinkingService,
    LimitationBasis,
    StatementKind,
    StatementSupportStatus,
)
from paperpilot.demo.fake_reader import FakeReader
from paperpilot.demo.fake_verifier import FakeVerifier
from paperpilot.demo.seed import create_demo_seed
from paperpilot.verification import VerificationStatus, apply_verification


def make_result(index=0):
    seed = create_demo_seed()
    analysis = FakeReader().analyze(seed.documents[index])
    verification = FakeVerifier().verify(analysis, seed.documents[index])
    return seed, analysis, apply_verification(analysis, verification)


def test_all_statement_categories_are_linked_deterministically():
    seed, analysis, verified = make_result()
    first = EvidenceLinkingService().link(analysis, verified, seed.papers[0])
    second = EvidenceLinkingService().link(analysis, verified, seed.papers[0])
    assert first == second
    assert first.contributions[0].kind is StatementKind.CONTRIBUTION
    assert first.innovations[0].kind is StatementKind.INNOVATION
    assert first.findings[0].kind is StatementKind.FINDING
    assert first.limitations[0].kind is StatementKind.LIMITATION
    assert first.contributions[0].statement_key == second.contributions[0].statement_key


def test_statement_key_changes_with_kind_or_text():
    seed, analysis, verified = make_result()
    service = EvidenceLinkingService()
    result = service.link(analysis, verified, seed.papers[0])
    assert result.contributions[0].statement_key != result.innovations[0].statement_key


def test_supported_statement_is_grounded_when_locator_exists():
    seed, analysis, verified = make_result()
    statement = EvidenceLinkingService().link(analysis, verified, seed.papers[0]).contributions[0]
    assert statement.support_status is StatementSupportStatus.SUPPORTED
    assert statement.is_evidence_grounded
    assert statement.supporting_evidence_keys
    assert 0 < statement.confidence <= 1


def test_unmapped_statement_is_not_grounded():
    seed, analysis, verified = make_result()
    changed = analysis.model_copy(update={"contributions": ["unrelated statement with no overlap"]})
    result = EvidenceLinkingService().link(changed, verified, seed.papers[0])
    assert result.contributions[0].support_status is StatementSupportStatus.UNMAPPED
    assert not result.contributions[0].is_evidence_grounded
    assert "NO_SUPPORTING_EVIDENCE" in result.contributions[0].reasons


def test_unverified_evidence_is_not_support():
    seed, analysis, verified = make_result()
    verification = verified.verification.model_copy(
        update={
            "verified_evidence": [
                item.model_copy(update={"status": VerificationStatus.REJECTED})
                for item in verified.verification.verified_evidence
            ]
        }
    )
    rejected = verified.model_copy(update={"verification": verification})
    result = EvidenceLinkingService().link(analysis, rejected, seed.papers[0])
    assert result.contributions[0].support_status is StatementSupportStatus.UNSUPPORTED
    assert not result.contributions[0].is_evidence_grounded


def test_limitation_basis_is_conservative():
    seed, analysis, verified = make_result()
    result = EvidenceLinkingService().link(analysis, verified, seed.papers[0])
    assert result.limitations[0].statement_basis in {
        LimitationBasis.EVIDENCE_BOUND_OBSERVATION,
        LimitationBasis.READER_INFERENCE,
    }


def test_conflicting_evidence_gets_conflicted_status():
    seed, analysis, verified = make_result()
    first = verified.verification.verified_evidence[0]
    conflict = first.model_copy(
        update={
            "status": VerificationStatus.CONFLICTED,
            "evidence": first.evidence.model_copy(update={"id": uuid4()}),
        }
    )
    verification = verified.verification.model_copy(
        update={"verified_evidence": [first, conflict]}
    )
    conflicted = verified.model_copy(update={"verification": verification})
    result = EvidenceLinkingService().link(analysis, conflicted, seed.papers[0])
    assert result.contributions[0].support_status is StatementSupportStatus.CONFLICTED
    assert not result.contributions[0].is_evidence_grounded


def test_statistics_and_warnings_are_auditable():
    seed, analysis, verified = make_result()
    result = EvidenceLinkingService().link(analysis, verified, seed.papers[0])
    stats = result.linking_statistics
    assert stats.total_statements == 4
    assert stats.contribution_count == 1
    assert stats.innovation_count == 1
    assert stats.finding_count == 1
    assert stats.grounded_statements >= 2


def test_budget_is_deterministic_and_warns_on_truncation():
    seed, analysis, verified = make_result()
    expanded = analysis.model_copy(update={"contributions": ["one", "two", "three"]})
    from paperpilot.analysis import StatementLinkingBudget

    service = EvidenceLinkingService(budget=StatementLinkingBudget(max_contributions=1))
    result = service.link(expanded, verified, seed.papers[0])
    assert len(result.contributions) == 1
    assert "STATEMENT_LINKING_TRUNCATED" in result.warnings


def test_json_roundtrip_and_paper_identity():
    seed, analysis, verified = make_result()
    result = EvidenceLinkingService().link(analysis, verified, seed.papers[0])
    restored = type(result).model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.paper_id == analysis.paper_id


def test_cross_paper_evidence_is_ignored():
    seed, analysis, verified = make_result()
    other = verified.verification.verified_evidence[0].model_copy(
        update={"evidence": verified.verification.verified_evidence[0].evidence.model_copy(update={"paper_id": uuid4()})}
    )
    verification = verified.verification.model_copy(update={"verified_evidence": [other]})
    result = EvidenceLinkingService().link(analysis, verified.model_copy(update={"verification": verification}), seed.papers[0])
    assert result.contributions[0].support_status is StatementSupportStatus.UNMAPPED
    assert "CROSS_PAPER_EVIDENCE_LINK" in result.warnings


def test_dangling_summary_evidence_is_reported():
    seed, analysis, verified = make_result()
    changed_summary = analysis.method_summary.model_copy(update={"evidence_ids": [uuid4()]})
    changed = analysis.model_copy(update={"method_summary": changed_summary})
    result = EvidenceLinkingService().link(changed, verified, seed.papers[0])
    assert "DANGLING_EVIDENCE_KEY" in result.warnings


def test_no_input_mutation():
    seed, analysis, verified = make_result()
    before = analysis.model_dump_json()
    EvidenceLinkingService().link(analysis, verified, seed.papers[0])
    assert analysis.model_dump_json() == before
