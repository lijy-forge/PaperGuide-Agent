"""Unit tests for dependency-injected orchestration node adapters."""

import threading
import time
import unittest

from paperpilot.document import (
    DocumentIngestionResult,
    IngestionStatus,
    PaperIngestionItem,
)
from paperpilot.domain import (
    Author,
    FullTextStatus,
    EvidenceType,
    PaperCandidate,
    PaperSource,
    ResearchConfig,
)
from paperpilot.orchestration import (
    NextAction,
    OrchestratorConfig,
    ResearchStep,
    create_initial_state,
    state_to_json,
)
from paperpilot.orchestration.nodes import (
    IngestionNode,
    PlannerNode,
    QualityGateNode,
    ReaderNode,
    RetrieverNode,
    VerifierNode,
)
from paperpilot.pipeline import SearchResult
from paperpilot.verification import (
    ConflictRecord,
    EvidenceVerificationResult,
    NumericConsistencyResult,
    SupportLevel,
    VerificationInputError,
    VerificationStatus,
    VerifiedEvidence,
    apply_verification,
)

from .verification_fixtures import make_analysis, make_document


def make_config() -> ResearchConfig:
    return ResearchConfig(
        question="Analyze SLAM",
        max_papers=5,
        sources=[PaperSource.ARXIV],
    )


def make_state():
    config = make_config()
    return create_initial_state(config.question, config)


def make_paper(title: str = "Paper") -> PaperCandidate:
    return PaperCandidate(
        title=title,
        normalized_title=title.casefold(),
        abstract=None,
        authors=[Author(full_name="Ada Researcher", affiliations=[])],
        publication_year=2025,
        venue=None,
        doi=None,
        arxiv_id=None,
        semantic_scholar_id=None,
        openalex_id=None,
        sources=[PaperSource.ARXIV],
        landing_page_url=None,
        pdf_url="https://arxiv.org/pdf/2501.00001.pdf",
        citation_count=None,
        full_text_status=FullTextStatus.AVAILABLE,
        relevance_score=None,
        selection_reason=None,
    )


def make_ingestion_result(documents):
    items = [
        PaperIngestionItem(
            paper_id=document.paper_id,
            title=document.title,
            status=IngestionStatus.PARSED,
            document=document,
            downloaded_file_path=f"{document.paper_id}.pdf",
            content_hash="a" * 64,
            size_bytes=100,
            page_count=len(document.pages),
            warnings=[],
        )
        for document in documents
    ]
    return DocumentIngestionResult(
        items=items,
        documents=documents,
        total_requested=len(items),
        total_eligible=len(items),
        total_downloaded=len(items),
        total_parsed=len(items),
        total_skipped=0,
        total_failed=0,
        warnings=[],
    )


def make_verification(analysis, *, accepted_method=True, conflicted=False):
    evidence = analysis.evidence[0] if accepted_method else analysis.evidence[-1]
    status = VerificationStatus.CONFLICTED if conflicted else VerificationStatus.VERIFIED
    support = SupportLevel.UNSUPPORTED if conflicted else SupportLevel.DIRECT
    item = VerifiedEvidence(
        evidence=evidence.model_copy(
            update={
                "evidence_type": (
                    EvidenceType.UNSUPPORTED if conflicted else EvidenceType.DIRECT
                )
            },
            deep=True,
        ),
        claim=evidence.normalized_fact,
        source_field="method.summary" if accepted_method else "experiment.metric:ATE",
        status=status,
        support_level=support,
        entailment_score=0.0 if conflicted else 1.0,
        contradiction_score=0.9 if conflicted else 0.0,
        overclaim_detected=False,
        numeric_consistency=NumericConsistencyResult(
            claim_numbers=[],
            quote_numbers=[],
            missing_numbers=[],
            unit_matches=None,
            direction_matches=None,
            warnings=[],
        ),
        reasoning="Conflict detected." if conflicted else "Directly supported.",
        warnings=[],
        verifier_model="fake-verifier",
        prompt_version="v1",
    )
    conflicts = []
    if conflicted:
        conflicts = [
            ConflictRecord(
                evidence_ids=[evidence.id],
                claims=[evidence.normalized_fact],
                conflict_type="direction",
                description="Conflicting direction.",
                confidence=0.9,
                warnings=[],
            )
        ]
    return EvidenceVerificationResult(
        paper_id=analysis.paper_id,
        verified_evidence=[item],
        accepted_evidence_ids=[] if conflicted else [evidence.id],
        rejected_evidence_ids=[],
        conflicted_evidence_ids=[evidence.id] if conflicted else [],
        conflicts=conflicts,
        warnings=[],
        verification_score=0.0 if conflicted else 1.0,
        total_evidence=1,
        total_verified=0 if conflicted else 1,
        total_partial=0,
        total_rejected=0,
        total_conflicted=1 if conflicted else 0,
    )


class FakeSearchPipeline:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def search(self, config):
        self.calls.append(config)
        if self.error:
            raise self.error
        return self.result


class FakeIngestionPipeline:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def ingest(self, papers):
        self.calls.append(list(papers))
        if self.error:
            raise self.error
        return self.result


class FakeReader:
    def __init__(self, failing_ids=None):
        self.failing_ids = set(failing_ids or [])
        self.calls = []

    def analyze(self, document):
        self.calls.append(document.paper_id)
        if document.paper_id in self.failing_ids:
            raise RuntimeError("reader failed")
        return make_analysis(document)[0]


class FakeVerifier:
    def __init__(self, *, accepted_method=True):
        self.accepted_method = accepted_method
        self.calls = []

    def verify(self, analysis, document):
        self.calls.append(analysis.paper_id)
        return make_verification(analysis, accepted_method=self.accepted_method)


class TestOrchestrationNodes(unittest.TestCase):
    def test_planner_success(self):
        result = PlannerNode().execute(make_state())

        self.assertEqual(result["current_step"], ResearchStep.PLANNING)
        self.assertEqual(result["next_action"], NextAction.RETRIEVE)

    def test_planner_empty_question_fails(self):
        state = make_state()
        state["question"] = " "

        result = PlannerNode().execute(state)

        self.assertEqual(result["current_step"], ResearchStep.FAILED)
        self.assertEqual(result["next_action"], NextAction.ABORT)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0].stage, ResearchStep.PLANNING)

    def test_retriever_updates_papers(self):
        paper = make_paper()
        search_result = SearchResult(
            papers=[paper],
            source_results={"arxiv": 1},
            source_errors={},
            warnings=["search warning"],
            total_found=1,
            total_after_dedup=1,
        )

        result = RetrieverNode(FakeSearchPipeline(search_result)).execute(make_state())

        self.assertEqual(result["papers"], [paper])
        self.assertEqual(result["search_result"], search_result)
        self.assertEqual(result["next_action"], NextAction.INGEST)

    def test_retriever_exception_is_isolated(self):
        result = RetrieverNode(
            FakeSearchPipeline(error=RuntimeError("search unavailable"))
        ).execute(make_state())

        self.assertEqual(result["next_action"], NextAction.EVALUATE_QUALITY)
        self.assertEqual(result["current_step"], ResearchStep.RETRIEVAL)
        self.assertEqual(len(result["errors"]), 1)

    def test_retriever_source_error_is_nonfatal_when_candidates_exist(self):
        paper = make_paper()
        search_result = SearchResult(
            papers=[paper],
            source_results={"arxiv": 1},
            source_errors={"semantic_scholar": "rate limited"},
            warnings=["Retriever semantic_scholar failed: rate limited"],
            total_found=1,
            total_after_dedup=1,
        )

        result = RetrieverNode(FakeSearchPipeline(search_result)).execute(make_state())

        self.assertEqual(result["next_action"], NextAction.INGEST)
        self.assertEqual(result["errors"], [])
        self.assertIn("Retriever semantic_scholar failed: rate limited", result["warnings"])

    def test_ingestion_generates_documents(self):
        document = make_document()
        paper = make_paper()
        paper = paper.model_copy(update={"id": document.paper_id})
        state = make_state()
        state["papers"] = [paper]
        pipeline = FakeIngestionPipeline(make_ingestion_result([document]))

        result = IngestionNode(pipeline).execute(state)

        self.assertEqual(result["documents"][str(document.paper_id)], document)
        self.assertEqual(result["next_action"], NextAction.READ)

    def test_ingestion_does_not_reprocess_existing_document(self):
        document = make_document()
        paper = make_paper().model_copy(update={"id": document.paper_id})
        state = make_state()
        state["papers"] = [paper]
        state["documents"] = {str(document.paper_id): document}
        pipeline = FakeIngestionPipeline()

        result = IngestionNode(pipeline).execute(state)

        self.assertEqual(pipeline.calls, [])
        self.assertEqual(result["documents"][str(document.paper_id)], document)

    def test_ingestion_has_bounded_concurrency_and_stable_document_order(self):
        class ConcurrentPipeline:
            def __init__(self):
                self.active = self.maximum_active = 0
                self.lock = threading.Lock()

            def ingest(self, papers):
                paper = papers[0]
                with self.lock:
                    self.active += 1
                    self.maximum_active = max(self.maximum_active, self.active)
                time.sleep(0.02)
                with self.lock:
                    self.active -= 1
                document = make_document().model_copy(
                    update={"paper_id": paper.id, "title": paper.title}
                )
                return make_ingestion_result([document])

        papers = [make_paper(f"Paper {index}") for index in range(5)]
        state = make_state()
        state["papers"] = papers
        pipeline = ConcurrentPipeline()

        result = IngestionNode(pipeline, max_concurrency=3).execute(state)

        self.assertLessEqual(pipeline.maximum_active, 3)
        self.assertGreaterEqual(pipeline.maximum_active, 2)
        self.assertEqual(list(result["documents"]), [str(paper.id) for paper in papers])

    def test_reader_isolates_one_paper_failure_and_continues(self):
        first = make_document()
        second = make_document()
        state = make_state()
        state["documents"] = {
            str(first.paper_id): first,
            str(second.paper_id): second,
        }
        reader = FakeReader(failing_ids={first.paper_id})

        result = ReaderNode(reader).execute(state)

        self.assertNotIn(str(first.paper_id), result["analyses"])
        self.assertIn(str(second.paper_id), result["analyses"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(reader.calls), 2)

    def test_verifier_generates_verified_results(self):
        analysis, document = make_analysis()
        key = str(document.paper_id)
        state = make_state()
        state["documents"] = {key: document}
        state["analyses"] = {key: analysis}

        result = VerifierNode(FakeVerifier()).execute(state)

        self.assertIn(key, result["verification_results"])
        self.assertIn(key, result["verified_results"])
        self.assertEqual(result["next_action"], NextAction.EVALUATE_QUALITY)

    def test_verifier_has_bounded_concurrency_and_stable_result_order(self):
        class ConcurrentVerifier(FakeVerifier):
            def __init__(self):
                super().__init__()
                self.active = self.maximum_active = 0
                self.lock = threading.Lock()

            def verify(self, analysis, document):
                with self.lock:
                    self.active += 1
                    self.maximum_active = max(self.maximum_active, self.active)
                time.sleep(0.02)
                with self.lock:
                    self.active -= 1
                return make_verification(analysis)

        documents = [make_document() for _ in range(4)]
        state = make_state()
        state["documents"] = {str(document.paper_id): document for document in documents}
        state["analyses"] = {
            str(document.paper_id): make_analysis(document)[0] for document in documents
        }
        verifier = ConcurrentVerifier()

        result = VerifierNode(verifier, max_concurrency=3).execute(state)

        self.assertLessEqual(verifier.maximum_active, 3)
        self.assertGreaterEqual(verifier.maximum_active, 2)
        self.assertEqual(
            list(result["verification_results"]),
            [str(document.paper_id) for document in documents],
        )

    def test_verifier_apply_failure_preserves_raw_verification(self):
        analysis, document = make_analysis()
        key = str(document.paper_id)
        state = make_state()
        state["documents"] = {key: document}
        state["analyses"] = {key: analysis}

        def fail_apply(analysis, verification):
            raise VerificationInputError("no evidence accepted")

        result = VerifierNode(
            FakeVerifier(),
            apply_verification_fn=fail_apply,
        ).execute(state)

        self.assertIn(key, result["verification_results"])
        self.assertNotIn(key, result["verified_results"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(result["errors"][0].recoverable)
        self.assertEqual(result["errors"][0].stage, ResearchStep.VERIFICATION)
        self.assertEqual(result["errors"][0].paper_id, analysis.paper_id)

    def test_verifier_preserves_verified_experiment_without_method_evidence(self):
        analysis, document = make_analysis()
        key = str(document.paper_id)
        state = make_state()
        state["documents"] = {key: document}
        state["analyses"] = {key: analysis}

        result = VerifierNode(FakeVerifier(accepted_method=False)).execute(state)

        self.assertIn(key, result["verification_results"])
        self.assertIn(key, result["verified_results"])
        self.assertEqual(
            result["verified_results"][key].verified_method_summary.evidence_ids,
            [],
        )
        self.assertEqual(result["errors"], [])

    def test_quality_gate_passes(self):
        analysis, document = make_analysis()
        verification = make_verification(analysis)
        verified = apply_verification(analysis, verification)
        state = make_state()
        key = str(document.paper_id)
        state["verified_results"] = {key: verified}
        state["verification_results"] = {key: verification}

        result = QualityGateNode(OrchestratorConfig()).execute(state)

        self.assertEqual(result["next_action"], NextAction.COMPLETE)

    def test_quality_gate_allows_degraded_result(self):
        analysis, document = make_analysis()
        verification = make_verification(analysis)
        verified = apply_verification(analysis, verification)
        state = make_state()
        key = str(document.paper_id)
        state["verified_results"] = {key: verified}
        state["verification_results"] = {key: verification}
        config = OrchestratorConfig(minimum_verified_papers=2)

        result = QualityGateNode(config).execute(state)

        self.assertEqual(result["next_action"], NextAction.COMPLETE_DEGRADED)

    def test_quality_gate_routes_conflict_to_human_review(self):
        analysis, document = make_analysis()
        conflict = make_verification(analysis, conflicted=True)
        state = make_state()
        state["verification_results"] = {str(document.paper_id): conflict}

        result = QualityGateNode(OrchestratorConfig()).execute(state)

        self.assertEqual(result["next_action"], NextAction.HUMAN_REVIEW)
        self.assertTrue(result["quality_summary"]["has_conflicts"])

    def test_node_does_not_modify_input_state(self):
        state = make_state()
        before = state_to_json(state)

        result = PlannerNode().execute(state)

        self.assertEqual(state_to_json(state), before)
        self.assertIsNot(result, state)

    def test_keyboard_interrupt_is_not_swallowed(self):
        pipeline = FakeSearchPipeline(error=KeyboardInterrupt())

        with self.assertRaises(KeyboardInterrupt):
            RetrieverNode(pipeline).execute(make_state())


if __name__ == "__main__":
    unittest.main()
