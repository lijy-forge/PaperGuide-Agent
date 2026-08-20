"""PyMuPDF-backed text extraction and heuristic section detection."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from paperpilot.domain import PaperCandidate

from .exceptions import PdfParseError
from .models import Document, Page, Section


class PdfParser:
    """Parse PDF pages and identify common academic section headings."""

    _COMMON_SECTION_RE = re.compile(
        r"^(?:(?:\d+(?:\.\d+)*|[IVXLC]+)[.)]?\s+)?"
        r"(?:abstract|introduction|related\s+work|background|"
        r"methods?|methodology|proposed\s+method|"
        r"experiments?|experimental\s+(?:setup|results)|results|"
        r"discussion|conclusions?)$",
        re.IGNORECASE,
    )
    _NUMBERED_SECTION_RE = re.compile(
        r"^(?:\d+(?:\.\d+)*|[IVXLC]+)[.)]?\s+[^\W\d_].+$",
        re.IGNORECASE,
    )
    MAX_HEADING_CHARACTERS = 120
    MAX_HEADING_WORDS = 12

    def __init__(self, pymupdf_module: Any | None = None):
        self._pymupdf_module = pymupdf_module

    def parse(
        self, pdf_path: str | Path, paper: PaperCandidate
    ) -> Document:
        """Parse a local PDF into page text and heuristic sections."""

        path = Path(pdf_path)
        if not path.is_file():
            raise PdfParseError(f"PDF file does not exist: {path}")
        pymupdf = self._pymupdf_module or self._load_pymupdf()

        try:
            with pymupdf.open(str(path)) as pdf:
                pages = [
                    Page(
                        page_number=index + 1,
                        text=(page.get_text("text") or "").strip(),
                    )
                    for index, page in enumerate(pdf)
                ]
                raw_metadata = getattr(pdf, "metadata", {}) or {}
                pdf_metadata = (
                    dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
                )
        except Exception as error:
            raise PdfParseError(f"Unable to parse PDF {path}: {error}") from error

        return Document(
            paper_id=paper.id,
            title=paper.title,
            source_path=str(path.resolve()),
            pages=pages,
            sections=self._detect_sections(pages),
            metadata={
                "page_count": len(pages),
                "parser": "pymupdf",
                "pdf_metadata": pdf_metadata,
            },
        )

    @classmethod
    def _detect_sections(cls, pages: list[Page]) -> list[Section]:
        lines: list[tuple[int, str]] = []
        for page in pages:
            lines.extend(
                (page.page_number, line.strip())
                for line in page.text.splitlines()
                if line.strip()
            )

        heading_indices = [
            index for index, (_, line) in enumerate(lines) if cls._is_heading(line)
        ]
        sections: list[Section] = []
        for heading_position, start_index in enumerate(heading_indices):
            end_index = (
                heading_indices[heading_position + 1]
                if heading_position + 1 < len(heading_indices)
                else len(lines)
            )
            section_lines = lines[start_index:end_index]
            if not section_lines:
                continue
            sections.append(
                Section(
                    title=section_lines[0][1],
                    page_start=section_lines[0][0],
                    page_end=section_lines[-1][0],
                    text="\n".join(line for _, line in section_lines),
                )
            )
        return sections

    @classmethod
    def _is_heading(cls, line: str) -> bool:
        if not line or len(line) > cls.MAX_HEADING_CHARACTERS:
            return False
        if len(line.split()) > cls.MAX_HEADING_WORDS:
            return False
        if cls._COMMON_SECTION_RE.fullmatch(line):
            return True
        if cls._NUMBERED_SECTION_RE.fullmatch(line):
            return True

        cased_letters = [
            character
            for character in line
            if character.isalpha() and character.lower() != character.upper()
        ]
        return bool(cased_letters) and line == line.upper()

    @staticmethod
    def _load_pymupdf() -> Any:
        try:
            import fitz

            return fitz
        except ImportError:
            try:
                import pymupdf

                return pymupdf
            except ImportError as error:
                raise PdfParseError(
                    "PyMuPDF is required to parse PDFs; install the repository's "
                    "pymupdf dependency"
                ) from error
