"""Deterministic and explainable candidate-paper matching."""

from difflib import SequenceMatcher

from pydantic import BaseModel, ConfigDict, Field

from paperpilot.domain import PaperCandidate

from .metadata_normalizer import MetadataNormalizer


class PaperMatchResult(BaseModel):
    """Explain whether two candidates represent the same paper."""

    model_config = ConfigDict(extra="forbid")

    is_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    matched_by: list[str]
    reasons: list[str]


class PaperMatcher:
    """Match paper candidates using identifiers and lightweight metadata rules."""

    DOI_CONFIDENCE = 0.99
    ARXIV_CONFIDENCE = 0.98
    SEMANTIC_SCHOLAR_CONFIDENCE = 0.97
    OPENALEX_CONFIDENCE = 0.96
    IDENTIFIER_CONFLICT_PENALTY = 0.04

    EXACT_TITLE_CONFIDENCE = 0.90
    EXACT_TITLE_MISSING_YEAR_CONFIDENCE = 0.86
    FUZZY_TITLE_CONFIDENCE = 0.82
    FUZZY_TITLE_THRESHOLD = 0.90
    SHORT_TITLE_FUZZY_THRESHOLD = 0.97
    AUTHOR_OVERLAP_THRESHOLD = 0.50
    SHORT_TITLE_AUTHOR_THRESHOLD = 0.75
    MAX_YEAR_DIFFERENCE = 1
    SHORT_TITLE_MAX_TOKENS = 4
    SHORT_TITLE_MAX_CHARACTERS = 28

    def match(self, left: PaperCandidate, right: PaperCandidate) -> PaperMatchResult:
        """Return a deterministic, explainable match result for two papers."""

        doi_left = MetadataNormalizer.normalize_doi(left.doi)
        doi_right = MetadataNormalizer.normalize_doi(right.doi)
        arxiv_left = MetadataNormalizer.normalize_arxiv_id(left.arxiv_id)
        arxiv_right = MetadataNormalizer.normalize_arxiv_id(right.arxiv_id)

        doi_conflict = bool(doi_left and doi_right and doi_left != doi_right)
        arxiv_conflict = bool(
            arxiv_left and arxiv_right and arxiv_left != arxiv_right
        )
        conflict_reasons = self._conflict_reasons(doi_conflict, arxiv_conflict)

        if doi_left and doi_left == doi_right:
            return self._identifier_match(
                "doi", self.DOI_CONFIDENCE, conflict_reasons
            )
        if arxiv_left and arxiv_left == arxiv_right:
            return self._identifier_match(
                "arxiv_id", self.ARXIV_CONFIDENCE, conflict_reasons
            )

        for attribute, label, confidence in (
            (
                "semantic_scholar_id",
                "semantic_scholar_id",
                self.SEMANTIC_SCHOLAR_CONFIDENCE,
            ),
            ("openalex_id", "openalex_id", self.OPENALEX_CONFIDENCE),
        ):
            left_id = self._normalize_external_id(getattr(left, attribute))
            right_id = self._normalize_external_id(getattr(right, attribute))
            if left_id and left_id == right_id:
                return self._identifier_match(label, confidence, conflict_reasons)

        title_left = MetadataNormalizer.normalize_title(left.title)
        title_right = MetadataNormalizer.normalize_title(right.title)
        if not title_left or not title_right:
            return PaperMatchResult(
                is_match=False,
                confidence=0.0,
                matched_by=[],
                reasons=["One or both normalized titles are empty."],
            )

        author_overlap = self._author_overlap(left, right)
        year_difference = self._year_difference(left, right)
        is_short = self._is_short_title(title_left) or self._is_short_title(
            title_right
        )

        if doi_conflict:
            return PaperMatchResult(
                is_match=False,
                confidence=0.10,
                matched_by=[],
                reasons=conflict_reasons
                + ["A DOI conflict blocks title-based matching."],
            )

        if title_left == title_right:
            return self._match_exact_title(
                author_overlap,
                year_difference,
                is_short,
                arxiv_conflict,
                conflict_reasons,
            )

        similarity = SequenceMatcher(None, title_left, title_right).ratio()
        threshold = (
            self.SHORT_TITLE_FUZZY_THRESHOLD
            if is_short
            else self.FUZZY_TITLE_THRESHOLD
        )
        required_author_overlap = (
            self.SHORT_TITLE_AUTHOR_THRESHOLD
            if is_short
            else self.AUTHOR_OVERLAP_THRESHOLD
        )
        reasons = [
            f"Normalized title similarity is {similarity:.3f} (threshold {threshold:.3f}).",
            f"Author overlap is {author_overlap:.3f} (threshold {required_author_overlap:.3f}).",
        ] + conflict_reasons

        if (
            similarity >= threshold
            and author_overlap >= required_author_overlap
            and year_difference is not None
            and year_difference <= self.MAX_YEAR_DIFFERENCE
            and not arxiv_conflict
        ):
            reasons.append(
                f"Publication years differ by {year_difference}, within the allowed range."
            )
            return PaperMatchResult(
                is_match=True,
                confidence=self.FUZZY_TITLE_CONFIDENCE,
                matched_by=["fuzzy_title", "authors", "publication_year"],
                reasons=reasons,
            )

        if year_difference is None:
            reasons.append("Fuzzy title matching requires publication years on both records.")
        elif year_difference > self.MAX_YEAR_DIFFERENCE:
            reasons.append(
                f"Publication years differ by {year_difference}, exceeding the allowed range."
            )
        if arxiv_conflict:
            reasons.append("An arXiv ID conflict blocks fuzzy title matching.")
        return PaperMatchResult(
            is_match=False,
            confidence=min(similarity, 0.79),
            matched_by=[],
            reasons=reasons,
        )

    def _match_exact_title(
        self,
        author_overlap: float,
        year_difference: int | None,
        is_short: bool,
        arxiv_conflict: bool,
        conflict_reasons: list[str],
    ) -> PaperMatchResult:
        required_author_overlap = (
            self.SHORT_TITLE_AUTHOR_THRESHOLD
            if is_short
            else self.AUTHOR_OVERLAP_THRESHOLD
        )
        reasons = [
            "Normalized titles are identical.",
            f"Author overlap is {author_overlap:.3f} (threshold {required_author_overlap:.3f}).",
        ] + conflict_reasons
        year_matches = year_difference is None or year_difference <= self.MAX_YEAR_DIFFERENCE
        if year_difference is None:
            reasons.append("At least one publication year is unavailable.")
        else:
            reasons.append(f"Publication years differ by {year_difference}.")

        if is_short and year_difference != 0:
            reasons.append("A short title requires the same known publication year.")
            year_matches = False
        if arxiv_conflict:
            reasons.append("An arXiv ID conflict blocks title-only matching.")
            year_matches = False

        if author_overlap >= required_author_overlap and year_matches:
            confidence = (
                self.EXACT_TITLE_CONFIDENCE
                if year_difference is not None
                else self.EXACT_TITLE_MISSING_YEAR_CONFIDENCE
            )
            return PaperMatchResult(
                is_match=True,
                confidence=confidence,
                matched_by=["normalized_title", "authors", "publication_year"],
                reasons=reasons,
            )
        return PaperMatchResult(
            is_match=False,
            confidence=0.55 if author_overlap else 0.25,
            matched_by=[],
            reasons=reasons,
        )

    def _identifier_match(
        self,
        identifier: str,
        confidence: float,
        conflict_reasons: list[str],
    ) -> PaperMatchResult:
        adjusted = max(
            0.0,
            confidence - self.IDENTIFIER_CONFLICT_PENALTY * len(conflict_reasons),
        )
        return PaperMatchResult(
            is_match=True,
            confidence=adjusted,
            matched_by=[identifier],
            reasons=[f"Normalized {identifier} values are identical."]
            + conflict_reasons,
        )

    @staticmethod
    def _conflict_reasons(doi_conflict: bool, arxiv_conflict: bool) -> list[str]:
        reasons: list[str] = []
        if doi_conflict:
            reasons.append("The records contain conflicting DOI values.")
        if arxiv_conflict:
            reasons.append("The records contain conflicting arXiv ID values.")
        return reasons

    @staticmethod
    def _normalize_external_id(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/").casefold()
        return normalized or None

    @staticmethod
    def _year_difference(
        left: PaperCandidate, right: PaperCandidate
    ) -> int | None:
        if left.publication_year is None or right.publication_year is None:
            return None
        return abs(left.publication_year - right.publication_year)

    @classmethod
    def _author_overlap(
        cls, left: PaperCandidate, right: PaperCandidate
    ) -> float:
        left_names = {
            MetadataNormalizer.normalize_author_name(
                author.normalized_name or author.full_name
            )
            for author in left.authors
        }
        right_names = {
            MetadataNormalizer.normalize_author_name(
                author.normalized_name or author.full_name
            )
            for author in right.authors
        }
        left_names.discard("")
        right_names.discard("")
        if not left_names or not right_names:
            return 0.0
        return len(left_names & right_names) / min(len(left_names), len(right_names))

    @classmethod
    def _is_short_title(cls, title: str) -> bool:
        return (
            len(title.split()) <= cls.SHORT_TITLE_MAX_TOKENS
            or len(title) <= cls.SHORT_TITLE_MAX_CHARACTERS
        )
