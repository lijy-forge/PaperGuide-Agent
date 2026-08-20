"""Exact and whitespace-tolerant mapping of LLM evidence to Documents."""

import re
from collections import Counter
from uuid import UUID

from paperpilot.document import Document, Section
from paperpilot.domain import Evidence, EvidenceType, SourceLocator

from .models import EvidenceMappingResult, EvidenceReference


class EvidenceMapper:
    """Map only locatable verbatim evidence references into domain Evidence."""

    _NUMBERING_RE = re.compile(
        r"^\s*(?:(?:\d+(?:\.\d+)*|[IVXLC]+)[.)]?\s+)", re.IGNORECASE
    )

    def map(
        self, references: list[EvidenceReference], document: Document
    ) -> EvidenceMappingResult:
        """Verify quotes and return evidence plus deterministic diagnostics."""

        counts = Counter(reference.evidence_key for reference in references)
        evidence: list[Evidence] = []
        key_to_id: dict[str, UUID] = {}
        warnings: list[str] = []
        rejected_keys: list[str] = []

        for reference in references:
            key = reference.evidence_key
            if counts[key] > 1:
                self._reject(
                    key,
                    f"Evidence key {key!r} is duplicated and was rejected.",
                    warnings,
                    rejected_keys,
                )
                continue

            location = self._locate(reference, document)
            if isinstance(location, str):
                self._reject(key, location, warnings, rejected_keys)
                continue
            text, section, page_start, page_end = location
            match = self._find_quote(text, reference.quote)
            if match is None:
                self._reject(
                    key,
                    f"Evidence key {key!r} quote was not found at its declared location.",
                    warnings,
                    rejected_keys,
                )
                continue

            item = Evidence(
                paper_id=document.paper_id,
                evidence_type=EvidenceType.DIRECT,
                quote=text[match.start() : match.end()],
                normalized_fact=reference.claim,
                locator=SourceLocator(
                    paper_id=document.paper_id,
                    section_title=section.title if section is not None else None,
                    page_start=page_start,
                    page_end=page_end,
                    char_start=match.start(),
                    char_end=match.end(),
                ),
                confidence=reference.confidence,
            )
            evidence.append(item)
            key_to_id[key] = item.id

        return EvidenceMappingResult(
            evidence=evidence,
            key_to_id=key_to_id,
            warnings=self._stable_unique(warnings),
            rejected_keys=self._stable_unique(rejected_keys),
        )

    def _locate(
        self, reference: EvidenceReference, document: Document
    ) -> tuple[str, Section | None, int, int] | str:
        pages = {page.page_number: page for page in document.pages}
        page = pages.get(reference.page_number) if reference.page_number else None
        if reference.page_number is not None and page is None:
            return (
                f"Evidence key {reference.evidence_key!r} declares a page outside "
                "the document."
            )

        section = None
        if reference.section_title:
            section = self._find_section(reference.section_title, document.sections)
            if section is None:
                return (
                    f"Evidence key {reference.evidence_key!r} declares an unknown section."
                )
            if page is not None and not (
                section.page_start <= page.page_number <= section.page_end
            ):
                return (
                    f"Evidence key {reference.evidence_key!r} page is outside its "
                    "declared section."
                )

        if page is not None:
            return page.text, section, page.page_number, page.page_number
        if section is not None:
            return section.text, section, section.page_start, section.page_end

        for candidate in document.pages:
            if self._find_quote(candidate.text, reference.quote) is not None:
                return (
                    candidate.text,
                    None,
                    candidate.page_number,
                    candidate.page_number,
                )
        return (
            f"Evidence key {reference.evidence_key!r} quote was not found in the document."
        )

    @classmethod
    def _find_section(
        cls, requested_title: str, sections: list[Section]
    ) -> Section | None:
        normalized_requested = cls._normalize_title(requested_title)
        return next(
            (
                section
                for section in sections
                if cls._normalize_title(section.title) == normalized_requested
            ),
            None,
        )

    @staticmethod
    def _find_quote(text: str, quote: str) -> re.Match[str] | None:
        tokens = re.findall(r"\S+", quote.strip())
        if not tokens:
            return None
        pattern = r"\s+".join(re.escape(token) for token in tokens)
        return re.search(pattern, text)

    @classmethod
    def _normalize_title(cls, title: str) -> str:
        return cls._NUMBERING_RE.sub("", title).strip().casefold()

    @staticmethod
    def _reject(
        key: str,
        warning: str,
        warnings: list[str],
        rejected_keys: list[str],
    ) -> None:
        warnings.append(warning)
        rejected_keys.append(key)

    @staticmethod
    def _stable_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
