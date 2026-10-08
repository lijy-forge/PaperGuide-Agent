"""Combine several sources' rankings into one order.

Each source returns its own ranked list, and the scores behind those rankings
are not comparable across sources: one reports a relevance float, another
reports nothing, and a third orders by citation count. Concatenating the lists
and re-ranking the pile throws away what each source knew, and lets whichever
source returned the most results dominate the pool — measured here, Crossref
supplied 43 of 47 candidates while never carrying a PDF.

Reciprocal rank fusion uses only the position a paper reached in each list, so
no score has to be comparable. A paper two sources both rank highly outranks
one that a single source ranked first, which is the property worth having when
the sources disagree about what matters.
"""

from collections.abc import Iterable
from uuid import UUID

#: Damping constant from the original formulation. Large enough that the top
#: few positions do not dwarf everything below them, so agreement across
#: sources can outweigh one source's first place.
DEFAULT_K = 60


def reciprocal_rank_score(rank: int, *, k: int = DEFAULT_K) -> float:
    """Score one appearance at ``rank`` (0-based) in a source's list."""

    if rank < 0:
        raise ValueError("rank must not be negative")
    return 1.0 / (k + rank + 1)


def fuse(
    contributions: dict[UUID, float],
    merged_groups: Iterable[tuple[UUID, Iterable[UUID]]],
) -> dict[UUID, float]:
    """Fold each duplicate's score into the canonical paper that absorbed it.

    Deduplication runs before fusion, so a paper found by three sources exists
    once by then. Its score has to gather what every copy contributed, or
    appearing in several sources — the signal fusion exists to reward — would
    instead be lost by merging.
    """

    fused = dict(contributions)
    for canonical_id, duplicate_ids in merged_groups:
        total = fused.get(canonical_id, 0.0)
        for duplicate_id in duplicate_ids:
            total += contributions.get(duplicate_id, 0.0)
        fused[canonical_id] = total
    return fused
