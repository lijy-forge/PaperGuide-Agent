"""Deterministic vector timeline fishbone presentation."""

from __future__ import annotations

from collections import defaultdict
from html import escape
from typing import Sequence

from .citations import LiteratureTimelineEntry


class TimelineFishboneRenderer:
    """Render selected CORE timeline entries as safe vector SVG."""

    def __init__(self, *, width: int = 1200, node_width: int = 210, max_text_chars: int = 90) -> None:
        self.width = width
        self.node_width = node_width
        self.max_text_chars = max_text_chars

    def render(self, entries: Sequence[LiteratureTimelineEntry]) -> str:
        ordered = self._ordered(entries)
        if not ordered:
            return ""
        if len(ordered) > 10:
            groups = self.render_groups(ordered)
            return groups[0] if groups else ""
        height = 230 if len(ordered) <= 3 else 300
        spine_y = height // 2
        step = (self.width - 120 - self.node_width) / max(1, len(ordered) - 1)
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {height}" role="img" aria-label="Literature timeline">', '<rect width="100%" height="100%" fill="white"/>', f'<line x1="50" y1="{spine_y}" x2="{self.width - 50}" y2="{spine_y}" stroke="#334155" stroke-width="2"/>']
        for index, entry in enumerate(ordered):
            x = int(60 + self.node_width / 2 + index * step)
            above = index % 2 == 0
            node_y = spine_y - 68 if above else spine_y + 68
            parts.append(f'<line x1="{x}" y1="{spine_y}" x2="{x}" y2="{node_y + (26 if above else -26)}" stroke="#64748b" stroke-width="1.5"/>')
            parts.append(f'<circle cx="{x}" cy="{spine_y}" r="5" fill="#0f766e"/>')
            parts.append(self._node(entry, x - self.node_width // 2, node_y, above))
        parts.append("</svg>")
        return "".join(parts)

    def render_groups(self, entries: Sequence[LiteratureTimelineEntry]) -> list[str]:
        return [self.render(group) for group in self.group_entries(entries)]

    def group_entries(self, entries: Sequence[LiteratureTimelineEntry]) -> list[list[LiteratureTimelineEntry]]:
        """Return deterministic family/time chunks for multi-page consumers."""
        ordered = self._ordered(entries)
        if len(ordered) <= 10:
            return [ordered] if ordered else []
        grouped: dict[str, list[LiteratureTimelineEntry]] = defaultdict(list)
        for entry in ordered:
            grouped[entry.method_family or "Unclassified"].append(entry)
        output: list[list[LiteratureTimelineEntry]] = []
        for family in sorted(grouped):
            subset = grouped[family]
            for start in range(0, len(subset), 10):
                output.append(subset[start:start + 10])
        return output

    @staticmethod
    def _ordered(entries: Sequence[LiteratureTimelineEntry]) -> list[LiteratureTimelineEntry]:
        return sorted(entries, key=lambda item: (item.year is None, item.year or 0, item.authors_short.casefold(), item.short_title.casefold(), item.citation_number))

    def _node(self, entry: LiteratureTimelineEntry, x: int, y: int, above: bool) -> str:
        title = self._truncate(entry.short_title)
        contribution = self._truncate(entry.primary_contribution or "No verified contribution evidence")
        limitation = self._truncate(entry.primary_limitation or "No verified limitation evidence")
        year = str(entry.year) if entry.year is not None else "Year unavailable"
        text_y = y + (0 if above else 16)
        lines = [f"{year} [{entry.citation_number}] {title}", f"Contribution: {contribution}", f"Limitation: {limitation}"]
        rect_y = y - 48 if above else y
        parts = [f'<rect x="{x}" y="{rect_y}" width="{self.node_width}" height="62" fill="#f8fafc" stroke="#94a3b8"/>']
        for offset, line in enumerate(lines):
            parts.append(f'<text x="{x + 8}" y="{rect_y + 16 + offset * 16}" font-family="sans-serif" font-size="11" fill="#0f172a">{escape(line)}</text>')
        return "".join(parts)

    def _truncate(self, value: str) -> str:
        value = " ".join(value.split())
        return value if len(value) <= self.max_text_chars else value[: self.max_text_chars - 1] + "…"
