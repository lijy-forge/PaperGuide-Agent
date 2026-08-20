"""Dependency-free deterministic checks for evidence locations and literals."""

import re

from pydantic import BaseModel, ConfigDict

from paperpilot.document import Document

from .models import (
    DeterministicCheckResult,
    EvidenceClaim,
    NumericConsistencyResult,
)


class DeterministicEvidenceConfig(BaseModel):
    """Centralized vocabulary used by deterministic consistency checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    units: tuple[str, ...] = (
        "%",
        "ms",
        "s",
        "fps",
        "hz",
        "mb",
        "gb",
        "m",
        "cm",
        "mm",
        "degree",
        "°",
        "accuracy",
        "precision",
        "recall",
        "f1",
        "ate",
        "rmse",
    )
    positive_directions: tuple[str, ...] = (
        "higher",
        "increase",
        "increased",
        "improve",
        "improved",
        "outperform",
        "outperforms",
        "faster",
        "better",
        "提升",
        "提高",
        "增加",
        "优于",
        "更快",
        "更好",
    )
    negative_directions: tuple[str, ...] = (
        "lower",
        "decrease",
        "decreased",
        "reduce",
        "reduced",
        "slower",
        "worse",
        "下降",
        "降低",
        "减少",
        "更慢",
        "更差",
    )


class DeterministicEvidenceChecker:
    """Validate location integrity and literal numeric consistency without an LLM."""

    _NUMBER_RE = re.compile(r"(?<![\w.])[+-]?(?:\d*\.\d+|\d+(?:,\d{3})*)%?")

    def __init__(self, config: DeterministicEvidenceConfig | None = None):
        self.config = config or DeterministicEvidenceConfig()

    def check(
        self, evidence_claim: EvidenceClaim, document: Document
    ) -> DeterministicCheckResult:
        """Check an EvidenceClaim without modifying it or its Document."""

        evidence = evidence_claim.evidence
        warnings: list[str] = []
        location_valid = evidence.paper_id == document.paper_id
        if not location_valid:
            warnings.append("Evidence paper_id does not match the document.")

        source_text = self._source_text(evidence_claim, document, warnings)
        if source_text is None:
            location_valid = False
            quote_valid = False
        else:
            quote_valid = self._validate_quote(evidence_claim, source_text, warnings)

        numeric = self._numeric_consistency(evidence_claim.claim, evidence.quote)
        warnings.extend(numeric.warnings)
        return DeterministicCheckResult(
            location_valid=location_valid,
            quote_valid=quote_valid,
            numeric_consistency=numeric,
            hard_reject=not location_valid or not quote_valid,
            warnings=self._stable_unique(warnings),
        )

    def _source_text(
        self, evidence_claim: EvidenceClaim, document: Document, warnings: list[str]
    ) -> str | None:
        locator = evidence_claim.evidence.locator
        pages = {page.page_number: page for page in document.pages}
        if locator.page_start is None or locator.page_end is None:
            warnings.append("Evidence locator does not contain a complete page range.")
            return None
        if locator.page_start > locator.page_end or any(
            page_number not in pages
            for page_number in range(locator.page_start, locator.page_end + 1)
        ):
            warnings.append("Evidence locator page range is outside the document.")
            return None

        page_text = "\n".join(
            pages[number].text
            for number in range(locator.page_start, locator.page_end + 1)
        )
        if locator.section_title:
            section = next(
                (
                    item
                    for item in document.sections
                    if item.title.casefold().strip()
                    == locator.section_title.casefold().strip()
                ),
                None,
            )
            if section is not None:
                # EvidenceMapper records offsets against page text when the LLM
                # supplies both a page and a section. Prefer whichever coordinate
                # space actually contains the quote at the recorded range.
                if self._range_matches_quote(
                    page_text,
                    locator.char_start,
                    locator.char_end,
                    evidence_claim.evidence.quote,
                ):
                    return page_text
                return section.text
        return page_text

    @classmethod
    def _range_matches_quote(
        cls,
        source_text: str,
        char_start: int | None,
        char_end: int | None,
        quote: str,
    ) -> bool:
        if char_start is None or char_end is None:
            return False
        if char_start < 0 or char_end < char_start or char_end > len(source_text):
            return False
        return cls._normalize_space(source_text[char_start:char_end]) == cls._normalize_space(
            quote
        )

    @classmethod
    def _validate_quote(
        cls, evidence_claim: EvidenceClaim, source_text: str, warnings: list[str]
    ) -> bool:
        evidence = evidence_claim.evidence
        locator = evidence.locator
        if not evidence.quote.strip() or not evidence_claim.claim.strip():
            warnings.append("Evidence quote or claim is empty.")
            return False

        if (locator.char_start is None) != (locator.char_end is None):
            warnings.append("Evidence character range is incomplete.")
            return False
        if locator.char_start is not None and locator.char_end is not None:
            if (
                locator.char_start < 0
                or locator.char_end < locator.char_start
                or locator.char_end > len(source_text)
            ):
                warnings.append("Evidence character range is outside source text.")
                return False
            located = source_text[locator.char_start : locator.char_end]
            if cls._normalize_space(located) != cls._normalize_space(evidence.quote):
                warnings.append("Evidence character range no longer matches its quote.")
                return False
            return True

        if cls._normalize_space(evidence.quote) not in cls._normalize_space(source_text):
            warnings.append("Evidence quote no longer exists at its source location.")
            return False
        return True

    def _numeric_consistency(
        self, claim: str, quote: str
    ) -> NumericConsistencyResult:
        claim_numbers = self._numbers(claim)
        quote_numbers = self._numbers(quote)
        missing_numbers = [number for number in claim_numbers if number not in quote_numbers]
        claim_units = self._units(claim)
        quote_units = self._units(quote)
        unit_matches = None if not claim_units else claim_units.issubset(quote_units)
        claim_direction = self._direction(claim)
        quote_direction = self._direction(quote)
        direction_matches = (
            None
            if claim_direction is None or quote_direction is None
            else claim_direction == quote_direction
        )

        warnings: list[str] = []
        if missing_numbers:
            warnings.append(
                "HIGH: claim numbers are absent from the quote: "
                + ", ".join(missing_numbers)
            )
        if unit_matches is False:
            warnings.append("Claim units are absent from or conflict with quote units.")
        if direction_matches is False:
            warnings.append("Claim and quote comparison directions conflict or are missing.")
        return NumericConsistencyResult(
            claim_numbers=claim_numbers,
            quote_numbers=quote_numbers,
            missing_numbers=missing_numbers,
            unit_matches=unit_matches,
            direction_matches=direction_matches,
            warnings=warnings,
        )

    @classmethod
    def _numbers(cls, text: str) -> list[str]:
        return list(
            dict.fromkeys(match.group(0).replace(",", "") for match in cls._NUMBER_RE.finditer(text))
        )

    def _units(self, text: str) -> set[str]:
        folded = text.casefold()
        found: set[str] = set()
        for unit in self.config.units:
            if unit in {"%", "°"}:
                if unit in folded:
                    found.add(unit)
            elif re.search(rf"(?<!\w){re.escape(unit)}(?!\w)", folded):
                found.add(unit)
        return found

    def _direction(self, text: str) -> str | None:
        folded = text.casefold()
        positive = any(term in folded for term in self.config.positive_directions)
        negative = any(term in folded for term in self.config.negative_directions)
        if positive == negative:
            return None
        return "positive" if positive else "negative"

    @staticmethod
    def _normalize_space(text: str) -> str:
        return " ".join(text.split())

    @staticmethod
    def _stable_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
