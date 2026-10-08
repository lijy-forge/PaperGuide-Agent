"""Why rejected evidence was rejected, counted by layer.

A rejection total says how much evidence was lost; it does not say what to fix.
These codes separate causes that call for different work, so the next change
targets the layer that produced the failure rather than the one that noticed
it:

- a quote the paper states in other words is a *reader* problem — it restated
  instead of quoting, and no amount of searching will make the text match;
- a quote nothing in the paper resembles is either fabricated or taken from a
  source this document is not;
- a locator that cannot be used at all is a mapping problem;
- evidence belonging to another paper is neither, and must never be relocated.

The split matters because each has a different answer, and only the counts can
say which one is actually costing evidence.
"""

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from paperguide.document import Document

from .models import EvidenceClaim

_WORD_RE = re.compile(r"[a-z0-9]+|[一-鿿]")

#: Above this share of the quote's own words present in the paper, the passage
#: is there and the wording is not: the reader paraphrased. Below it, nothing
#: in the paper resembles the quote.
_PARAPHRASE_SHARE = 0.8

PAPER_MISMATCH = "REJECTED_PAPER_MISMATCH"
LOCATOR_UNUSABLE = "REJECTED_LOCATOR_UNUSABLE"
QUOTE_PARAPHRASED = "REJECTED_QUOTE_PARAPHRASED"
QUOTE_ABSENT = "REJECTED_QUOTE_ABSENT"


class EvidenceRecoveryDiagnostic(BaseModel):
    """Counts for one paper: what was rejected, what came back, what did not."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hard_rejected: int = Field(default=0, ge=0)
    recovered: int = Field(default=0, ge=0)
    #: Which relocation strategy recovered each one, so a strategy that never
    #: fires can be removed instead of maintained.
    recovery_methods: dict[str, int] = Field(default_factory=dict)
    #: Why the rest stayed rejected. This is the number that decides whether
    #: more machinery here would help at all.
    unrecovered_reasons: dict[str, int] = Field(default_factory=dict)


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(unicodedata.normalize("NFKC", text).casefold())


def classify_rejection(claim: EvidenceClaim, document: Document) -> str:
    """Name the cause of a rejection that relocation could not repair."""

    if claim.evidence.paper_id != document.paper_id:
        return PAPER_MISMATCH

    quote_words = set(_words(claim.evidence.quote))
    if not quote_words:
        return LOCATOR_UNUSABLE

    present = set(_words(" ".join(page.text for page in document.pages)))
    share = len(quote_words & present) / len(quote_words)
    return QUOTE_PARAPHRASED if share >= _PARAPHRASE_SHARE else QUOTE_ABSENT
