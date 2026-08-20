"""Versioned prompt for independent semantic evidence verification."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paperpilot.verification.models import DeterministicCheckResult, EvidenceClaim

EVIDENCE_VERIFIER_PROMPT_VERSION = "v1"

EVIDENCE_VERIFIER_SYSTEM_PROMPT = """You are an evidence verifier, not a paper summarizer.
Judge only whether the supplied source text supports the exact claim. Never use
external knowledge and never change the quote. direct means the quote explicitly
states the claim; derived means the claim follows directly from multiple supplied
facts; inference means a reasonable interpretation not directly stated;
unsupported means the text does not support it. Numbers, units, datasets, metrics,
and comparison direction must agree. Mark overclaim_detected when the claim is
stronger or broader than the source. If source and claim contradict each other,
use conflicted or rejected. Do not accept a claim merely because it sounds
plausible. Return only the semantic assessment fields requested by the JSON schema.
The application binds the immutable Evidence ID and Claim itself."""


def build_evidence_verifier_prompt(
    evidence_claim: EvidenceClaim,
    deterministic: DeterministicCheckResult,
    neighboring_text: str,
) -> str:
    """Build a bounded prompt for one claim-evidence pair."""

    evidence = evidence_claim.evidence
    return f"""Verify this one claim against its source excerpt.

Evidence ID: {evidence.id}
Claim: {evidence_claim.claim}
Claim type: {evidence_claim.claim_type or 'unspecified'}
Source field: {evidence_claim.source_field or 'unspecified'}
Quote (immutable): {evidence.quote}
Page: {evidence.locator.page_start}
Section: {evidence.locator.section_title or 'unspecified'}

Neighboring source text:
{neighboring_text}

Deterministic checks:
{json.dumps(deterministic.model_dump(mode='json'), ensure_ascii=False, sort_keys=True)}
"""
