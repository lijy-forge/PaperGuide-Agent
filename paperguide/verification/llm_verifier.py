"""Bounded semantic verification through the shared structured LLM protocol."""

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from paperguide.analysis import AnalysisLLMError, StructuredLLMProtocol
from paperguide.document import Document
from paperguide.prompts import (
    EVIDENCE_VERIFIER_SYSTEM_PROMPT,
    build_evidence_verifier_prompt,
)

from .exceptions import LLMVerificationError
from .models import (
    DeterministicCheckResult,
    EvidenceClaim,
    EvidenceVerificationAssessment,
    EvidenceVerificationDecision,
)


class LLMEvidenceVerifierConfig(BaseModel):
    """Bounds for source text surrounding an evidence quote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_neighbor_characters: int = Field(default=800, ge=100, le=10_000)


class LLMEvidenceVerifier:
    """Ask an injected structured LLM to classify one located evidence claim."""

    def __init__(
        self,
        llm: StructuredLLMProtocol,
        config: LLMEvidenceVerifierConfig | None = None,
    ):
        self.llm = llm
        self.config = config or LLMEvidenceVerifierConfig()

    @property
    def model_name(self) -> str | None:
        """Return the injected model name when the adapter exposes one."""

        return getattr(self.llm, "model_name", None)

    def verify(
        self,
        evidence_claim: EvidenceClaim,
        deterministic: DeterministicCheckResult,
        document: Document,
    ) -> EvidenceVerificationDecision:
        """Verify one claim using only a bounded neighboring source excerpt."""

        neighboring_text = self._neighboring_text(evidence_claim, document)
        try:
            assessment = self.llm.generate_structured(
                system_prompt=EVIDENCE_VERIFIER_SYSTEM_PROMPT,
                user_prompt=build_evidence_verifier_prompt(
                    evidence_claim, deterministic, neighboring_text
                ),
                response_model=EvidenceVerificationAssessment,
            )
            if isinstance(assessment, EvidenceVerificationDecision):
                assessment_payload = assessment.model_dump(
                    exclude={"evidence_id", "claim"}
                )
                assessment = EvidenceVerificationAssessment.model_validate(
                    assessment_payload
                )
            elif not isinstance(assessment, EvidenceVerificationAssessment):
                assessment = EvidenceVerificationAssessment.model_validate(assessment)
            decision = EvidenceVerificationDecision(
                evidence_id=evidence_claim.evidence.id,
                claim=evidence_claim.claim,
                **assessment.model_dump(),
            )
        except (AnalysisLLMError, ValidationError) as error:
            raise LLMVerificationError(
                f"evidence verification failed: {type(error).__name__}"
            ) from error
        except Exception as error:
            raise LLMVerificationError(
                f"evidence verification failed: {type(error).__name__}"
            ) from error

        return decision

    def _neighboring_text(
        self, evidence_claim: EvidenceClaim, document: Document
    ) -> str:
        evidence = evidence_claim.evidence
        page = next(
            (
                item
                for item in document.pages
                if item.page_number == evidence.locator.page_start
            ),
            None,
        )
        text = page.text if page is not None else evidence.quote
        start = evidence.locator.char_start
        end = evidence.locator.char_end
        if start is None or end is None or start > len(text):
            quote_position = text.find(evidence.quote)
            start = max(0, quote_position)
            end = start + len(evidence.quote)

        budget = self.config.max_neighbor_characters
        left = max(0, start - budget // 2)
        right = min(len(text), max(end, start) + budget // 2)
        excerpt = text[left:right]
        if len(excerpt) > budget:
            excerpt = excerpt[:budget]
        return excerpt
