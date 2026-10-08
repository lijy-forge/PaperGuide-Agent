"""Find a quote in parsed PDF text despite typesetting.

A reader writes a quote as the words read; the parser returns what the file
holds. The two differ in ways that carry no meaning — a ligature is one
character ("ﬂ"), and a word that did not fit is split across lines with a
hyphen ("ofﬂoad-\\ning"). Matching the raw strings therefore misses a quote
the paper genuinely contains, and the evidence is discarded before anything
can verify it.

Locating is deliberately more lenient than storing. The search runs over a
normalized copy, but the offsets returned point into the original text, so the
evidence keeps the source's own characters and a later check still compares
against what the PDF actually says.
"""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s")

#: Hyphens are dropped on both sides rather than interpreted. Whether a hyphen
#: joins a split word or belongs to a compound cannot be told from the text,
#: and dropping it from the quote as well keeps the two comparable either way.
#: Two passages that differ only by hyphenation are the same passage.
_DROPPED = frozenset("-‐‑­")


def _normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """Return the normalized text and, per character, its index in the original."""

    out: list[str] = []
    offsets: list[int] = []
    previous_was_space = False
    just_dropped_hyphen = False
    for index, character in enumerate(text):
        if character in _DROPPED:
            just_dropped_hyphen = True
            continue
        if _WHITESPACE.match(character):
            # Whitespace right after a hyphen is the line break that split a
            # word, so it goes with the hyphen: "offload-\ning" is one word.
            if just_dropped_hyphen or previous_was_space or not out:
                continue
            out.append(" ")
            offsets.append(index)
            previous_was_space = True
            continue
        previous_was_space = False
        just_dropped_hyphen = False
        for expanded in unicodedata.normalize("NFKC", character).casefold():
            out.append(expanded)
            offsets.append(index)
    return "".join(out), offsets


def _normalize(text: str) -> str:
    return _normalize_with_offsets(text)[0]


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Return the quote's character range in ``text``, or None if it is absent.

    The range is expressed against the original text, not the normalized copy,
    so callers can slice the source exactly as it is written.
    """

    needle = _normalize(quote).strip()
    if not needle:
        return None

    haystack, offsets = _normalize_with_offsets(text)
    position = haystack.find(needle)
    if position < 0:
        return None

    start = offsets[position]
    # The end offset is exclusive, so it points one past the last matched
    # character of the original text rather than at it.
    end = offsets[position + len(needle) - 1] + 1
    return start, end
