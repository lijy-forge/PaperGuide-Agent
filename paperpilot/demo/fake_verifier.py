"""Deterministic offline evidence verifier compatible with VerifierNode."""

from paperpilot.analysis import PaperAnalysisResult
from paperpilot.document import Document
from paperpilot.verification import (
    EvidenceVerificationResult,
    NumericConsistencyResult,
    SupportLevel,
    VerificationStatus,
    VerifiedEvidence,
)


class FakeVerifier:
    """Accept seeded direct evidence while retaining normal verification models."""

    def verify(
        self,
        analysis: PaperAnalysisResult,
        document: Document,
    ) -> EvidenceVerificationResult:
        """Verify exact seeded quotes without calling an external provider."""

        if analysis.paper_id != document.paper_id:
            raise ValueError("analysis and document paper_id do not match")
        document_text = "\n".join(page.text for page in document.pages)
        verified: list[VerifiedEvidence] = []
        for evidence in analysis.evidence:
            if evidence.quote not in document_text:
                raise ValueError("seeded evidence quote is absent from document")
            verified.append(
                VerifiedEvidence(
                    evidence=evidence.model_copy(deep=True),
                    claim=evidence.normalized_fact,
                    claim_type="demo_fact",
                    source_field="evidence.normalized_fact",
                    status=VerificationStatus.VERIFIED,
                    support_level=SupportLevel.DIRECT,
                    entailment_score=0.95,
                    contradiction_score=0.0,
                    overclaim_detected=False,
                    numeric_consistency=NumericConsistencyResult(
                        claim_numbers=[],
                        quote_numbers=[],
                        missing_numbers=[],
                        unit_matches=None,
                        direction_matches=None,
                        warnings=[],
                    ),
                    reasoning=(
                        "The synthetic claim exactly matches its seeded source quote."
                    ),
                    warnings=[],
                    verifier_model="paperpilot-demo-verifier",
                    prompt_version="demo-v1",
                )
            )
        accepted_ids = [item.evidence.id for item in verified]
        return EvidenceVerificationResult(
            paper_id=analysis.paper_id,
            verified_evidence=verified,
            accepted_evidence_ids=accepted_ids,
            rejected_evidence_ids=[],
            conflicted_evidence_ids=[],
            conflicts=[],
            warnings=["Demo verification used deterministic exact-quote checks."],
            verification_score=0.95,
            total_evidence=len(verified),
            total_verified=len(verified),
            total_partial=0,
            total_rejected=0,
            total_conflicted=0,
        )
