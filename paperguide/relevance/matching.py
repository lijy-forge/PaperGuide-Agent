"""How a required concept is recognized in a paper's text.

The planner restates a question as concepts, and it writes them as compound
noun phrases — "multi-device collaborative computing". Requiring that phrase
to appear verbatim asks the literature to use the planner's exact wording,
which it does not: measured against 27 real candidates for such a question,
no paper contained all of its concepts as written, so nothing could ever be
classified core and no evidence could reach the report.

Matching on the concept's content words instead recognizes the paper that
says "collaborative computing across multiple devices". It is deliberately
conjunctive — every content word must be present — because the looser forms
admit a paper that merely shares one common word with the concept. The same
27 candidates, plus a control set of unrelated concepts, confirm the widening
matches real work without admitting the unrelated.

This applies to required concepts only. Exclusion concepts are matched by the
caller's own stricter rule: widening those would reject papers rather than
admit them, and their content words ("single", "device") are common enough in
any one field that the rule would fire almost everywhere.

Words are compared as written, with no stemming: a concept saying "object"
does not match a paper saying "objects". Stemming would widen the match
further and needs its own measurement against a control before it is worth
the behaviour change, so the limit is left visible here rather than hidden
behind a half-tested rule.
"""

import re

_WORD_RE = re.compile(r"[a-z0-9]+")

#: Words carrying no topical meaning, dropped before requiring a match. Kept
#: small on purpose: a word removed here is a word a concept no longer needs.
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "the",
        "of",
        "for",
        "in",
        "on",
        "to",
        "with",
        "based",
        "using",
        "via",
    }
)


def concept_tokens(concept: str) -> list[str]:
    """The content words a text must carry to count as covering this concept."""

    return [token for token in _WORD_RE.findall(concept) if token not in _STOP]


def concept_in_text(text: str, concept: str) -> bool:
    """Report whether a normalized text covers a normalized concept.

    Both arguments are expected to be normalized already by the caller, so
    this stays a pure token test and the two callers keep one normalizer each.
    """

    tokens = concept_tokens(concept)
    if not tokens:
        return False
    present = set(_WORD_RE.findall(text))
    return all(token in present for token in tokens)
