"""Remove the lines a publisher repeats on every page.

A journal PDF carries a licence notice, a running author name or a page
number on each page. The extractor returns them inline, so a sentence that
continues across a page break arrives with three lines of boilerplate wedged
into the middle of it. Measured over the 16 papers this project had already
downloaded, 14 carried such a line and 178 of 204 sentences that span a page
break were interrupted by one.

Everything downstream pays for that. The reader can quote across the seam or
misread a severed sentence, and the deterministic evidence check then rejects
a quote the paper genuinely contains — while no amount of work at that end can
repair it, because the passage is not contiguous in the text it is given.

Repetition is the only signal available here. The extractor is asked for plain
text, so there is no font size or page coordinate to judge by; but repeating in
the same position on most pages is what a running header *is*, which makes the
signal the definition rather than a proxy for it.
"""

import re

from .models import Page

_DIGITS = re.compile(r"\d+")

#: Only the top and bottom of a page are considered. A line repeated in the
#: body is content, and removing it would delete the paper's own words.
_ZONE_LINES = 3

#: Enough pages that a coincidence is implausible. A short paper skips the
#: whole procedure rather than risk a heading that happens to repeat twice.
_MIN_PAGES = 3
_MIN_SHARE = 0.5

#: A page never loses everything. Stated as "leaves nothing behind" rather than
#: as a share of the page: a share misfires on a short page, where removing the
#: one footer line is both correct and a large fraction of the text.


def _shape(line: str) -> str:
    """The line with digits blanked, so "Page 3" and "Page 4" are one shape."""

    return _DIGITS.sub("#", " ".join(line.split()))


def _zones(lines: list[str]) -> list[str]:
    if len(lines) <= _ZONE_LINES * 2:
        return list(lines)
    return [*lines[:_ZONE_LINES], *lines[-_ZONE_LINES:]]


def find_running_shapes(pages: list[Page]) -> set[str]:
    """Shapes that repeat at the top or bottom of most pages."""

    if len(pages) < _MIN_PAGES:
        return set()

    counts: dict[str, int] = {}
    for page in pages:
        lines = [line for line in page.text.splitlines() if line.strip()]
        # One page cannot vote twice for the same shape, or a page repeating a
        # line inside its own header block would clear the threshold alone.
        for shape in {_shape(line) for line in _zones(lines)}:
            counts[shape] = counts.get(shape, 0) + 1

    threshold = max(_MIN_PAGES, len(pages) * _MIN_SHARE)
    return {shape for shape, count in counts.items() if count >= threshold}


def strip_running_text(pages: list[Page]) -> tuple[list[Page], list[str]]:
    """Return the pages without their running header and footer lines.

    Also returns the removed lines, so a caller can record what was taken out
    instead of trusting that only boilerplate was.
    """

    shapes = find_running_shapes(pages)
    if not shapes:
        return list(pages), []

    cleaned: list[Page] = []
    removed: list[str] = []
    for page in pages:
        lines = page.text.splitlines()
        content = [line for line in lines if line.strip()]
        zone = set(_zones(content))
        keep: list[str] = []
        dropped: list[str] = []
        for line in lines:
            if line in zone and _shape(line) in shapes:
                dropped.append(line)
                continue
            keep.append(line)

        if content and len(dropped) == len(content):
            cleaned.append(page)
            continue

        removed.extend(dropped)
        cleaned.append(page.model_copy(update={"text": "\n".join(keep).strip()}))
    return cleaned, removed
