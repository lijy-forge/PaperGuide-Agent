"""Whether a candidate's full text can be fetched at all.

Two stages need this answer and must agree on it. Ingestion applies it to
decide what to download, and candidate selection applies it to decide what is
worth selecting: a paper whose full text cannot be fetched yields no evidence,
so reading it contributes nothing the report can cite. Keeping the rule in one
place is what stops the two from drifting into disagreement, which shows up as
a run that selects exactly the papers ingestion will skip.
"""

from paperguide.domain import FullTextStatus, PaperCandidate

from .metadata_normalizer import MetadataNormalizer

#: UNKNOWN is allowed because a source that does not report status may still
#: carry a usable link; the URL check below is what settles it.
INGESTIBLE_FULL_TEXT_STATUSES = frozenset(
    {FullTextStatus.AVAILABLE, FullTextStatus.UNKNOWN}
)


def can_ingest_full_text(paper: PaperCandidate) -> bool:
    """Report whether this candidate offers a full text worth trying to fetch."""

    if paper.full_text_status not in INGESTIBLE_FULL_TEXT_STATUSES:
        return False
    return MetadataNormalizer.normalize_url(paper.pdf_url) is not None
