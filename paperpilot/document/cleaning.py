"""Conservative deterministic cleanup of parsed paper text."""

import math
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from .models import Document, Page, Section

SECTION_SYNC_WARNING = (
    "Section text was preserved because repeated page headers or footers "
    "cannot be mapped to sections safely."
)


class DocumentCleaningConfig(BaseModel):
    """Thresholds and switches for deterministic document text cleanup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    collapse_blank_lines: bool = True
    remove_repeated_headers: bool = True
    remove_repeated_footers: bool = True
    repetition_ratio: float = Field(default=0.6, gt=0.0, le=1.0)
    minimum_repeated_pages: int = Field(default=3, ge=3)
    max_header_footer_length: int = Field(default=100, ge=1)


class DocumentTextCleaner:
    """Return a new Document with conservative whitespace and margin cleanup."""

    def __init__(self, config: DocumentCleaningConfig | None = None):
        self.config = config or DocumentCleaningConfig()

    def clean(self, document: Document) -> Document:
        """Clean page text without mutating the supplied document."""

        page_lines = [self._normalize_lines(page.text) for page in document.pages]
        headers = self._repeated_margin_lines(page_lines, at_start=True)
        footers = self._repeated_margin_lines(page_lines, at_start=False)
        removed_margin_text = False
        cleaned_pages: list[Page] = []

        for page, lines in zip(document.pages, page_lines):
            page_lines_copy = list(lines)
            if self.config.remove_repeated_headers:
                removed_margin_text |= self._remove_margin_line(
                    page_lines_copy, headers, at_start=True
                )
            if self.config.remove_repeated_footers:
                removed_margin_text |= self._remove_margin_line(
                    page_lines_copy, footers, at_start=False
                )
            cleaned_pages.append(
                Page(
                    page_number=page.page_number,
                    text=self._join_lines(page_lines_copy),
                )
            )

        metadata = dict(document.metadata)
        if removed_margin_text:
            sections = [section.model_copy(deep=True) for section in document.sections]
            warnings = list(metadata.get("cleaning_warnings", []))
            if SECTION_SYNC_WARNING not in warnings:
                warnings.append(SECTION_SYNC_WARNING)
            metadata["cleaning_warnings"] = warnings
        else:
            sections = [
                Section(
                    title=section.title,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    text=self._join_lines(self._normalize_lines(section.text)),
                )
                for section in document.sections
            ]

        return document.model_copy(
            update={"pages": cleaned_pages, "sections": sections, "metadata": metadata},
            deep=True,
        )

    def _normalize_lines(self, text: str) -> list[str]:
        return [line.rstrip() if line.strip() else "" for line in text.splitlines()]

    def _join_lines(self, lines: list[str]) -> str:
        if not self.config.collapse_blank_lines:
            return "\n".join(lines)

        collapsed: list[str] = []
        consecutive_blanks = 0
        for line in lines:
            if line:
                consecutive_blanks = 0
                collapsed.append(line)
            else:
                consecutive_blanks += 1
                if consecutive_blanks <= 2:
                    collapsed.append("")
        return "\n".join(collapsed)

    def _repeated_margin_lines(
        self, pages: list[list[str]], *, at_start: bool
    ) -> set[str]:
        enabled = (
            self.config.remove_repeated_headers
            if at_start
            else self.config.remove_repeated_footers
        )
        if not enabled or not pages:
            return set()

        candidates: list[str] = []
        for lines in pages:
            nonempty = [line for line in lines if line]
            if not nonempty:
                continue
            candidate = nonempty[0] if at_start else nonempty[-1]
            if len(candidate) <= self.config.max_header_footer_length:
                candidates.append(candidate)

        required = max(
            self.config.minimum_repeated_pages,
            math.ceil(len(pages) * self.config.repetition_ratio),
        )
        return {
            line for line, count in Counter(candidates).items() if count >= required
        }

    @staticmethod
    def _remove_margin_line(
        lines: list[str], repeated: set[str], *, at_start: bool
    ) -> bool:
        indices = range(len(lines)) if at_start else range(len(lines) - 1, -1, -1)
        for index in indices:
            if not lines[index]:
                continue
            if lines[index] in repeated:
                del lines[index]
                return True
            return False
        return False
