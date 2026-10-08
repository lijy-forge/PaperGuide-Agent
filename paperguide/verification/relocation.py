"""Look again for evidence the deterministic check could not locate.

A rejected claim has two very different causes. The quote may not be in the
paper, which is the rejection working. Or the quote is there and the recorded
coordinates are wrong — the reader named the wrong page, the passage straddles
a page boundary, the section title points somewhere the parser put other text.
Treating both as fraud discards evidence the paper genuinely contains.

What a relocator may do is deliberately narrow. It proposes **where to look**;
it never decides whether the evidence supports anything, and it cannot reach
the claim, the quote or the paper. Those are not rules a strategy is asked to
follow — a relocation has no field for them, so no strategy can express the
change. The verifier rebuilds the locator from the original, applying only the
coordinates below, then runs the same deterministic check and the same
isolated semantic verifier it would have run anyway.

One consequence is worth stating because it shapes every strategy here: a
relocator cannot lower the bar. Proposing an approximate match is pointless,
because the re-check compares the quote to the source exactly (after the
typesetting normalization both sides already share). The only useful proposal
is that the *same* passage sits somewhere else.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from paperguide.document import Document

from .deterministic import DeterministicEvidenceChecker
from .models import DeterministicCheckResult, EvidenceClaim


class EvidenceRelocation(BaseModel):
    """Coordinates to try instead, for the same quote in the same document.

    Carries no claim, no quote and no paper: the verifier copies those from the
    evidence being re-examined, so a relocation cannot move a claim onto a
    different source.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section_title: str | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    #: Which strategy produced this, recorded in the evidence warnings so a
    #: relocated citation is visible in the audit trail rather than silent.
    method: str


class EvidenceRelocator(Protocol):
    """Propose somewhere else to look, or decline."""

    def relocate(
        self,
        claim: EvidenceClaim,
        document: Document,
        failure: DeterministicCheckResult,
    ) -> EvidenceRelocation | None: ...


class FuzzyEvidenceRelocator:
    """Deterministic relocation: find the same passage elsewhere in the paper.

    No model and no network, so this runs in tests and offline. It covers the
    mistakes that can be stated as a rule — a wrong page number, a passage
    spanning two pages, a section title that no longer holds the text. What it
    cannot state as a rule it declines, leaving those for a strategy that can
    decide its own next step.
    """

    def __init__(self, *, max_page_span: int = 3) -> None:
        if max_page_span < 1:
            raise ValueError("max_page_span must be at least one")
        self._max_page_span = max_page_span
        self._matcher = DeterministicEvidenceChecker

    def relocate(
        self,
        claim: EvidenceClaim,
        document: Document,
        failure: DeterministicCheckResult,
    ) -> EvidenceRelocation | None:
        # A paper mismatch is not a location problem; moving the coordinates
        # would attach the claim to a document it never came from.
        if claim.evidence.paper_id != document.paper_id:
            return None

        quote = claim.evidence.quote
        if not quote.strip():
            return None

        pages = sorted(document.pages, key=lambda page: page.page_number)
        recorded = claim.evidence.locator.page_start

        single = self._single_page(quote, pages, recorded)
        if single is not None:
            return single
        return self._spanning_pages(quote, pages)

    def _single_page(self, quote, pages, recorded):
        for page in pages:
            if page.page_number == recorded:
                # Already tried, and the section title may have sent the check
                # to other text; retry this page without it before moving on.
                if self._matcher._passage_present(quote, page.text):
                    return EvidenceRelocation(
                        page_start=page.page_number,
                        page_end=page.page_number,
                        method="section_title_cleared",
                    )
                continue
            if self._matcher._passage_present(quote, page.text):
                return EvidenceRelocation(
                    page_start=page.page_number,
                    page_end=page.page_number,
                    method="quote_found_on_another_page",
                )
        return None

    def _spanning_pages(self, quote, pages):
        for span in range(2, self._max_page_span + 1):
            for index in range(len(pages) - span + 1):
                window = pages[index : index + span]
                joined = "\n".join(page.text for page in window)
                if self._matcher._passage_present(quote, joined):
                    return EvidenceRelocation(
                        page_start=window[0].page_number,
                        page_end=window[-1].page_number,
                        method="quote_spans_pages",
                    )
        return None
