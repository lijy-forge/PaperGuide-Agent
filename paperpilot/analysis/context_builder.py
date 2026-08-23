"""Deterministic construction of bounded, location-marked paper context."""

import re

from pydantic import BaseModel, ConfigDict, Field

from paperpilot.document import Document, Page, Section

from .exceptions import PaperContextError
from .models import PaperContext


class PaperContextConfig(BaseModel):
    """Limits and section preferences for Paper Reader context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_characters: int = Field(default=30_000, ge=100)
    max_pages: int = Field(default=20, ge=1)
    preferred_sections: tuple[str, ...] = (
        "abstract",
        "introduction",
        "contributions",
        "contribution",
        "limitations",
        "limitation",
        "discussion",
        "threats to validity",
        "conclusion",
        "future work",
        "method",
        "methodology",
        "proposed method",
        "experiment",
        "experiments",
        "experimental results",
        "results",
    )
    include_abstract: bool = True
    include_conclusion: bool = True
    minimum_section_characters: int = Field(default=20, ge=0)


class PaperContextBuilder:
    """Select high-value paper sections under deterministic size limits."""

    _NUMBERING_RE = re.compile(
        r"^\s*(?:(?:\d+(?:\.\d+)*|[IVXLC]+)[.)]?\s+)", re.IGNORECASE
    )

    def __init__(self, config: PaperContextConfig | None = None):
        self.config = config or PaperContextConfig()

    def build(self, document: Document) -> PaperContext:
        """Build controlled context without modifying the source document."""

        if not document.pages or not any(page.text.strip() for page in document.pages):
            raise PaperContextError("document contains no extractable page text")

        blocks, selected_sections, page_ranges, page_limited = self._section_blocks(
            document
        )
        warnings: list[str] = []
        if not blocks:
            blocks, page_ranges, page_limited = self._page_blocks(document.pages)
            selected_sections = []
            warnings.append(
                "Preferred sections were unavailable; context fell back to page text."
            )

        context_text, character_limited, included_blocks = self._fit_character_limit(
            blocks
        )
        selected_sections = selected_sections[:included_blocks]
        page_ranges = page_ranges[:included_blocks]
        if not context_text.strip():
            raise PaperContextError("document context is empty after applying limits")

        truncated = page_limited or character_limited
        if page_limited:
            warnings.append("Context was limited by max_pages.")
        if character_limited:
            warnings.append("Context was truncated at max_characters.")

        return PaperContext(
            document_id=document.id,
            paper_id=document.paper_id,
            title=document.title,
            selected_sections=selected_sections,
            page_ranges=page_ranges,
            context_text=context_text,
            token_estimate=(len(context_text) + 3) // 4,
            truncated=truncated,
            warnings=warnings,
        )

    def _section_blocks(
        self, document: Document
    ) -> tuple[list[str], list[str], list[tuple[int, int]], bool]:
        ranked: list[tuple[int, int, Section]] = []
        for index, section in enumerate(document.sections):
            normalized = self._normalize_section_title(section.title)
            rank = self._section_rank(normalized)
            if rank is None or len(section.text.strip()) < self.config.minimum_section_characters:
                continue
            ranked.append((rank, index, section))
        ranked.sort(key=lambda item: (item[0], item[1]))

        blocks: list[str] = []
        selected_sections: list[str] = []
        page_ranges: list[tuple[int, int]] = []
        selected_pages: set[int] = set()
        page_limited = False
        for _, _, section in ranked:
            section_pages = set(range(section.page_start, section.page_end + 1))
            new_pages = section_pages - selected_pages
            if len(selected_pages | new_pages) > self.config.max_pages:
                page_limited = True
                continue
            selected_pages.update(new_pages)
            page_label = self._page_label(section.page_start, section.page_end)
            blocks.append(
                f"[{page_label}][SECTION {section.title}]\n{section.text.strip()}"
            )
            selected_sections.append(section.title)
            page_ranges.append((section.page_start, section.page_end))
        return blocks, selected_sections, page_ranges, page_limited

    def _page_blocks(
        self, pages: list[Page]
    ) -> tuple[list[str], list[tuple[int, int]], bool]:
        usable = [page for page in pages if page.text.strip()]
        selected = usable[: self.config.max_pages]
        blocks = [f"[PAGE {page.page_number}]\n{page.text.strip()}" for page in selected]
        ranges = [(page.page_number, page.page_number) for page in selected]
        return blocks, ranges, len(usable) > len(selected)

    def _fit_character_limit(self, blocks: list[str]) -> tuple[str, bool, int]:
        separator = "\n\n"
        full_text = separator.join(blocks)
        if len(full_text) <= self.config.max_characters:
            return full_text, False, len(blocks)

        fitted: list[str] = []
        remaining = self.config.max_characters
        for block in blocks:
            prefix_length = len(separator) if fitted else 0
            if remaining <= prefix_length:
                break
            available = remaining - prefix_length
            if len(block) <= available:
                fitted.append(block)
                remaining -= prefix_length + len(block)
                continue
            marker_end = block.find("\n") + 1
            if marker_end <= 0 or available <= marker_end:
                break
            fitted.append(block[:available].rstrip())
            break
        return separator.join(fitted), True, len(fitted)

    def _section_rank(self, normalized_title: str) -> int | None:
        for index, preferred in enumerate(self.config.preferred_sections):
            normalized_preferred = preferred.casefold().strip()
            if self._matches_preferred(normalized_title, normalized_preferred):
                if normalized_preferred == "abstract" and not self.config.include_abstract:
                    return None
                if normalized_preferred == "conclusion" and not self.config.include_conclusion:
                    return None
                return index
        return None

    @staticmethod
    def _matches_preferred(normalized_title: str, preferred: str) -> bool:
        forms = {preferred}
        if not preferred.endswith("s"):
            forms.add(f"{preferred}s")
        return any(
            normalized_title == form or normalized_title.startswith(f"{form} ")
            for form in forms
        )

    @classmethod
    def _normalize_section_title(cls, title: str) -> str:
        return cls._NUMBERING_RE.sub("", title).strip().casefold()

    @staticmethod
    def _page_label(page_start: int, page_end: int) -> str:
        if page_start == page_end:
            return f"PAGE {page_start}"
        return f"PAGES {page_start}-{page_end}"
