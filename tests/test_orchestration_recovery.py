"""Unit tests for deterministic checkpoint recovery decisions."""

import copy
import unittest
from uuid import uuid4

from paperguide.domain import PaperSource, ResearchConfig
from paperguide.orchestration import (
    NextAction,
    OrchestratorConfig,
    ResearchStep,
    create_initial_state,
)
from paperguide.orchestration.checkpoint import (
    CheckpointRecord,
    MemoryCheckpointStore,
)
from paperguide.orchestration.recovery import (
    RecoveryAction,
    RecoveryDecision,
    RecoveryError,
    RecoveryService,
    RecoveryStateInvalidError,
)
from paperguide.verification import (
    EvidenceVerificationResult,
    VerifiedPaperAnalysisResult,
)
from pydantic import ValidationError

from .verification_fixtures import make_analysis, make_document


def make_state(question: str = "Analyze SLAM"):
    """Create a valid empty workflow state."""

    config = ResearchConfig(
        question=question,
        max_papers=5,
        sources=[PaperSource.ARXIV],
    )
    return create_initial_state(config.question, config)


def make_service(store=None, config=None):
    """Create a recovery service with deterministic in-memory dependencies."""

    return RecoveryService(
        store or MemoryCheckpointStore(),
        config or OrchestratorConfig(),
    )


def save_at_step(store, state, step, action=NextAction.EVALUATE_QUALITY):
    """Save a copied state at a selected workflow step."""

    snapshot = copy.deepcopy(state)
    snapshot["current_step"] = step
    snapshot["next_action"] = action
    store.save(snapshot["run_id"], snapshot)
    return snapshot


def add_analysis(state):
    """Add a valid document-analysis chain to state."""

    analysis, document = make_analysis()
    key = str(document.paper_id)
    state["documents"] = {key: document}
    state["analyses"] = {key: analysis}
    return analysis, document


def add_verified_result(state):
    """Add a minimal valid verified result and its prerequisite objects."""

    analysis, document = add_analysis(state)
    verification = EvidenceVerificationResult(
        paper_id=analysis.paper_id,
        verified_evidence=[],
        accepted_evidence_ids=[],
        rejected_evidence_ids=[],
        conflicted_evidence_ids=[],
        conflicts=[],
        warnings=[],
        verification_score=0.0,
        total_evidence=0,
        total_verified=0,
        total_partial=0,
        total_rejected=0,
        total_conflicted=0,
    )
    verified = VerifiedPaperAnalysisResult(
        original_analysis=analysis,
        verification=verification,
        verified_method_summary=analysis.method_summary,
        verified_experiment_summary=analysis.experiment_summary,
        verified_contributions=[],
        verified_limitations=[],
        warnings=[],
    )
    key = str(document.paper_id)
    state["verification_results"] = {key: verification}
    state["verified_results"] = {key: verified}


class InvalidStateStore:
    """Return a deliberately unvalidated checkpoint record for one test."""

    def __init__(self, record):
        self.record = record

    def load(self, run_id):
        return self.record


class OrchestrationRecoveryTests(unittest.TestCase):
    """Verify recovery actions, retry limits, validation, and state isolation."""

    def test_successfully_recovers_checkpoint(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        store.save(state["run_id"], state)

        decision = make_service(store).recover(state["run_id"])

        self.assertEqual(decision.action, RecoveryAction.RESUME)
        self.assertEqual(decision.state["run_id"], state["run_id"])

    def test_missing_run_id_raises_recovery_error(self) -> None:
        service = make_service()

        with self.assertRaises(RecoveryError):
            service.recover(uuid4())

    def test_invalid_state_is_rejected(self) -> None:
        state = make_state()
        invalid = copy.deepcopy(state)
        invalid["question"] = "Mismatched question"
        record = CheckpointRecord.model_construct(
            run_id=state["run_id"],
            state=invalid,
        )
        service = make_service(InvalidStateStore(record))

        with self.assertRaises(RecoveryStateInvalidError):
            service.recover(state["run_id"])

    def test_retrieval_without_papers_retries(self) -> None:
        store = MemoryCheckpointStore()
        state = save_at_step(store, make_state(), ResearchStep.RETRIEVAL)

        decision = make_service(store).recover(state["run_id"])

        self.assertEqual(decision.action, RecoveryAction.RETRY)
        self.assertEqual(decision.retry_stage, "retrieval")
        self.assertEqual(decision.remaining_attempts, 2)

    def test_ingestion_with_documents_resumes(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        document = make_document()
        state["documents"] = {str(document.paper_id): document}
        state = save_at_step(store, state, ResearchStep.INGESTION)

        decision = make_service(store).recover(state["run_id"])

        self.assertEqual(decision.action, RecoveryAction.RESUME)

    def test_reading_with_analyses_resumes(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        add_analysis(state)
        state = save_at_step(store, state, ResearchStep.READING)

        decision = make_service(store).recover(state["run_id"])

        self.assertEqual(decision.action, RecoveryAction.RESUME)

    def test_verification_with_verified_results_resumes(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        add_verified_result(state)
        state = save_at_step(store, state, ResearchStep.VERIFICATION)

        decision = make_service(store).recover(state["run_id"])

        self.assertEqual(decision.action, RecoveryAction.RESUME)

    def test_quality_complete_is_terminal(self) -> None:
        store = MemoryCheckpointStore()
        state = save_at_step(
            store,
            make_state(),
            ResearchStep.QUALITY_GATE,
            NextAction.COMPLETE,
        )

        decision = make_service(store).recover(state["run_id"])

        self.assertEqual(decision.action, RecoveryAction.COMPLETE)

    def test_quality_degraded_is_terminal(self) -> None:
        store = MemoryCheckpointStore()
        state = save_at_step(
            store,
            make_state(),
            ResearchStep.QUALITY_GATE,
            NextAction.COMPLETE_DEGRADED,
        )

        decision = make_service(store).recover(state["run_id"])

        self.assertEqual(decision.action, RecoveryAction.COMPLETE_DEGRADED)

    def test_quality_human_review_is_terminal(self) -> None:
        store = MemoryCheckpointStore()
        state = save_at_step(
            store,
            make_state(),
            ResearchStep.QUALITY_GATE,
            NextAction.HUMAN_REVIEW,
        )

        decision = make_service(store).recover(state["run_id"])

        self.assertEqual(decision.action, RecoveryAction.HUMAN_REVIEW)

    def test_recovery_state_is_isolated(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        store.save(state["run_id"], state)
        original = copy.deepcopy(state)

        decision = make_service(store).recover(state["run_id"])
        decision.state["warnings"].append("consumer mutation")

        self.assertEqual(state, original)
        self.assertEqual(store.load(state["run_id"]).state["warnings"], [])

    def test_retry_budget_exhaustion_aborts(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        state["attempts"] = {ResearchStep.RETRIEVAL.value: 2}
        state = save_at_step(store, state, ResearchStep.RETRIEVAL)

        decision = make_service(store).recover(state["run_id"])

        self.assertEqual(decision.action, RecoveryAction.ABORT)
        self.assertEqual(decision.remaining_attempts, 0)
        self.assertEqual(decision.failed_stage, ResearchStep.RETRIEVAL)

    def test_decision_json_round_trip(self) -> None:
        store = MemoryCheckpointStore()
        state = make_state()
        store.save(state["run_id"], state)
        decision = make_service(store).recover(state["run_id"])

        restored = RecoveryDecision.model_validate_json(decision.model_dump_json())

        self.assertEqual(restored, decision)

    def test_decision_rejects_unknown_fields(self) -> None:
        state = make_state()

        with self.assertRaises(ValidationError):
            RecoveryDecision(
                action=RecoveryAction.RESUME,
                reason="resume",
                state=state,
                failed_stage=None,
                retry_stage=None,
                remaining_attempts=0,
                unexpected=True,
            )


if __name__ == "__main__":
    unittest.main()
