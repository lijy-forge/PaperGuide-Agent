"""Deterministic citation, reference, evidence-ledger, and timeline data."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from paperpilot.analysis import (
    EvidenceLinkedPaperAnalysis,
    EvidenceLinkedStatement,
    LimitationBasis,
    StatementKind,
    StatementSupportStatus,
)
from paperpilot.domain import Author, PaperCandidate, SourceLocator
from paperpilot.orchestration import ResearchState
from paperpilot.relevance import FinalRelevanceAssessment, FinalRelevanceClassification
from paperpilot.verification import VerificationStatus, VerifiedPaperAnalysisResult


class CitationRegistryError(ValueError):
    """Raised when deterministic citation data cannot be assembled safely."""


class ReferenceIntegrityValidator:
    """Validate citation/reference/ledger integrity without inspecting prose."""

    def validate(self, data: "SurveyEvidenceData") -> None:
        CitationRegistry._validate(data.citation_registry)
        citation_numbers = {item.citation_number for item in data.citation_registry}
        reference_numbers = {item.citation_number for item in data.references}
        if citation_numbers != reference_numbers:
            raise CitationRegistryError("every citation must have exactly one reference")
        if any(item.citation_number not in citation_numbers for item in data.evidence_ledger):
            raise CitationRegistryError("ledger contains a dangling citation number")
        selected = {item.citation_number for item in data.citation_registry if item.selected_for_report}
        if any(item.citation_number not in selected for item in data.core_paper_profiles):
            raise CitationRegistryError("core profile references a non-selected citation")


class CitationEntry(BaseModel):
    """Internal citation entry with stable public citation number."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_number: int = Field(ge=1)
    paper_id: UUID
    canonical_identifier: str
    title: str
    authors: list[str]
    first_author: str | None = None
    publication_year: int | None = Field(default=None, ge=1)
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    semantic_scholar_id: str | None = None
    openalex_id: str | None = None
    source_url: str | None = None
    sources: list[str] = Field(default_factory=list)
    full_text_status: str = "unknown"
    final_relevance: str | None = None
    selected_for_report: bool = False

    def public_dict(self) -> dict:
        """Return reference metadata without internal matching identifiers."""

        return self.model_dump(exclude={"paper_id", "canonical_identifier"}, mode="json")


class ReferenceEntry(BaseModel):
    """Public metadata reference derived directly from paper metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_number: int = Field(ge=1)
    authors: list[str]
    title: str
    year: int | None = Field(default=None, ge=1)
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    semantic_scholar_id: str | None = None
    openalex_id: str | None = None
    source_url: str | None = None
    sources: list[str] = Field(default_factory=list)
    full_text_status: str = "unknown"


class EvidenceLedgerEntry(BaseModel):
    """One statement-to-verified-evidence row for audit and appendix data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_number: int = Field(ge=1)
    statement_key: str
    statement_kind: StatementKind
    statement_text: str
    support_status: StatementSupportStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_key_internal: str
    verification_status: VerificationStatus
    entailment_score: float = Field(ge=0.0, le=1.0)
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    quote: str
    limitation_basis: LimitationBasis | None = None
    conflict_status: bool = False

    def public_dict(self) -> dict:
        """Return a public ledger row without internal statement/evidence keys."""

        return self.model_dump(exclude={"statement_key", "evidence_key_internal"}, mode="json")


class CorePaperProfile(BaseModel):
    """Deterministic profile for a selected CORE paper."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_number: int = Field(ge=1)
    title: str
    authors: list[str]
    year: int | None = Field(default=None, ge=1)
    venue: str | None = None
    method_summary: str
    research_problem: str
    primary_contribution: EvidenceLinkedStatement | None = None
    primary_limitation: EvidenceLinkedStatement | None = None
    additional_contributions: list[EvidenceLinkedStatement]
    additional_limitations: list[EvidenceLinkedStatement]
    key_findings: list[EvidenceLinkedStatement]
    verified_evidence_count: int = Field(ge=0)
    grounded_statement_count: int = Field(ge=0)
    evidence_confidence_summary: float = Field(ge=0.0, le=1.0)
    contribution_availability: str = "NO_VERIFIED_CONTRIBUTION"
    limitation_availability: str
    source_url: str | None = None
    sources: list[str] = Field(default_factory=list)
    full_text_status: str = "unknown"

    def public_dict(self) -> dict:
        """Return profile content without raw evidence identifiers."""

        payload = self.model_dump(mode="json")
        for field in ("primary_contribution", "primary_limitation"):
            if payload.get(field):
                for key in ("statement_key", "supporting_evidence_keys", "contradicting_evidence_keys", "unsupported_evidence_keys"):
                    payload[field].pop(key, None)
        for field in ("additional_contributions", "additional_limitations", "key_findings"):
            for statement in payload[field]:
                for key in ("statement_key", "supporting_evidence_keys", "contradicting_evidence_keys", "unsupported_evidence_keys"):
                    statement.pop(key, None)
        return payload


class LiteratureTimelineEntry(BaseModel):
    """Compact timeline data for selected CORE papers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_number: int = Field(ge=1)
    paper_id: UUID
    year: int | None = Field(default=None, ge=1)
    year_unknown: bool = False
    authors_short: str
    short_title: str
    primary_contribution: str | None = None
    contribution_kind: str = "contribution"
    contribution_status: StatementSupportStatus | None = None
    contribution_evidence_keys: list[str]
    primary_limitation: str | None = None
    limitation_status: StatementSupportStatus | None = None
    limitation_basis: LimitationBasis | None = None
    limitation_evidence_keys: list[str]
    source_url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    semantic_scholar_id: str | None = None
    openalex_id: str | None = None
    sources: list[str] = Field(default_factory=list)
    full_text_status: str = "unknown"
    contribution_availability: str = "NO_VERIFIED_CONTRIBUTION"
    limitation_availability: str = "AUTHOR_LIMITATION_NOT_LOCATED"
    method_family: str | None = None
    selected_for_report: bool = True

    def public_dict(self) -> dict:
        """Return timeline metadata without internal IDs."""

        return self.model_dump(
            exclude={"paper_id", "contribution_evidence_keys", "limitation_evidence_keys"},
            mode="json",
        )


class FishboneReadinessAssessment(BaseModel):
    """Deterministic quality summary for future fishbone rendering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_core_entries: int = Field(ge=0)
    entries_with_grounded_contribution: int = Field(ge=0)
    entries_with_grounded_limitation: int = Field(ge=0)
    entries_missing_contribution: int = Field(ge=0)
    entries_missing_limitation: int = Field(ge=0)
    year_coverage: list[int]
    ready: bool


class SurveyEvidenceData(BaseModel):
    """Complete deterministic data foundation consumed by a future survey writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_registry: list[CitationEntry]
    references: list[ReferenceEntry]
    core_paper_profiles: list[CorePaperProfile]
    evidence_ledger: list[EvidenceLedgerEntry]
    literature_timeline: list[LiteratureTimelineEntry]
    fishbone_readiness: FishboneReadinessAssessment
    warnings: list[str]

    def public_dict(self) -> dict:
        """Return public data with internal evidence identifiers removed."""

        payload = self.model_dump(mode="json")
        for entry in payload["citation_registry"]:
            entry.pop("paper_id", None)
            entry.pop("canonical_identifier", None)
        for entry in payload["literature_timeline"]:
            entry.pop("paper_id", None)
            entry.pop("contribution_evidence_keys", None)
            entry.pop("limitation_evidence_keys", None)
        for entry in payload["evidence_ledger"]:
            entry.pop("statement_key", None)
            entry.pop("evidence_key_internal", None)
        for profile in payload["core_paper_profiles"]:
            for field in ("primary_contribution", "primary_limitation"):
                statement = profile.get(field)
                if statement:
                    for key in ("statement_key", "supporting_evidence_keys", "contradicting_evidence_keys", "unsupported_evidence_keys"):
                        statement.pop(key, None)
            for field in ("additional_contributions", "additional_limitations", "key_findings"):
                for statement in profile.get(field, []):
                    for key in ("statement_key", "supporting_evidence_keys", "contradicting_evidence_keys", "unsupported_evidence_keys"):
                        statement.pop(key, None)
        return payload


class SurveyEvidenceDataBuilder:
    """Assemble all citation and evidence data without LLM calls."""

    def build(
        self,
        papers: Sequence[PaperCandidate],
        final_relevance: Mapping[UUID, FinalRelevanceAssessment] | None,
        linked_analyses: Mapping[str, EvidenceLinkedPaperAnalysis],
        verified_results: Mapping[str, VerifiedPaperAnalysisResult],
    ) -> SurveyEvidenceData:
        paper_by_id = {paper.id: paper for paper in papers}
        registry = CitationRegistry().build(paper_by_id.values(), final_relevance)
        citation_by_paper = {entry.paper_id: entry for entry in registry}
        warnings: list[str] = []
        references = [self._reference(entry) for entry in registry]
        ledger: list[EvidenceLedgerEntry] = []
        profiles: list[CorePaperProfile] = []
        timeline: list[LiteratureTimelineEntry] = []
        for entry in registry:
            linked = linked_analyses.get(str(entry.paper_id))
            verified = verified_results.get(str(entry.paper_id))
            if linked is None or verified is None:
                warnings.append("MISSING_LINKED_ANALYSIS")
                continue
            evidence = {str(item.evidence.id): item for item in verified.verification.verified_evidence}
            ledger.extend(self._ledger(entry, linked, evidence))
            if not entry.selected_for_report:
                continue
            profile = self._profile(entry, linked, evidence, verified)
            profiles.append(profile)
            timeline.append(self._timeline(entry, linked))
        timeline.sort(key=lambda item: (item.year is None, item.year or 0, item.authors_short.casefold(), item.short_title.casefold(), item.citation_number))
        readiness = self._readiness(timeline)
        if not readiness.ready:
            warnings.append("FISHBONE_DATA_INCOMPLETE")
        data = SurveyEvidenceData(
            citation_registry=registry,
            references=references,
            core_paper_profiles=profiles,
            evidence_ledger=sorted(ledger, key=lambda item: (item.citation_number, item.statement_kind.value, item.statement_key, item.page or 0, item.evidence_key_internal)),
            literature_timeline=timeline,
            fishbone_readiness=readiness,
            warnings=list(dict.fromkeys(warnings)),
        )
        ReferenceIntegrityValidator().validate(data)
        return data

    def build_from_state(self, state: ResearchState) -> SurveyEvidenceData:
        """Build survey data from a validated orchestration state."""

        raw_relevance = state.get("final_relevance") or {}
        final_relevance = {
            UUID(str(key)): value for key, value in raw_relevance.items()
        }
        return self.build(
            state["papers"],
            final_relevance or None,
            state.get("evidence_linked_analysis", {}),
            state["verified_results"],
        )

    @staticmethod
    def _reference(entry: CitationEntry) -> ReferenceEntry:
        return ReferenceEntry(
            citation_number=entry.citation_number,
            authors=list(entry.authors),
            title=entry.title,
            year=entry.publication_year,
            venue=entry.venue,
            doi=entry.doi,
            arxiv_id=entry.arxiv_id,
            semantic_scholar_id=entry.semantic_scholar_id,
            openalex_id=entry.openalex_id,
            source_url=entry.source_url,
            sources=list(entry.sources),
            full_text_status=entry.full_text_status,
        )

    def _ledger(self, entry, linked, evidence):
        rows = []
        for statement in [*linked.contributions, *linked.innovations, *linked.limitations, *linked.findings]:
            keys = [*statement.supporting_evidence_keys, *statement.contradicting_evidence_keys, *statement.unsupported_evidence_keys]
            for key in dict.fromkeys(keys):
                item = evidence.get(key)
                if item is None or item.evidence.paper_id != entry.paper_id:
                    continue
                locator = item.evidence.locator
                rows.append(EvidenceLedgerEntry(
                    citation_number=entry.citation_number,
                    statement_key=statement.statement_key,
                    statement_kind=statement.kind,
                    statement_text=statement.text,
                    support_status=statement.support_status,
                    confidence=statement.confidence,
                    evidence_key_internal=key,
                    verification_status=item.status,
                    entailment_score=item.entailment_score,
                    page=locator.page_start,
                    section=locator.section_title,
                    quote=item.evidence.quote,
                    limitation_basis=statement.statement_basis,
                    conflict_status=bool(statement.contradicting_evidence_keys),
                ))
        return rows

    def _profile(self, entry, linked, evidence, verified):
        contributions = list(linked.contributions)
        limitations = list(linked.limitations)
        grounded_contrib = [item for item in contributions if item.is_evidence_grounded and item.support_status is StatementSupportStatus.SUPPORTED]
        if not grounded_contrib:
            grounded_contrib = [item for item in contributions if item.is_evidence_grounded and item.support_status is StatementSupportStatus.PARTIALLY_SUPPORTED]
        grounded_lim = [item for item in limitations if item.is_evidence_grounded and item.statement_basis in {LimitationBasis.AUTHOR_STATED, LimitationBasis.EVIDENCE_BOUND_OBSERVATION}]
        return CorePaperProfile(
            citation_number=entry.citation_number,
            title=entry.title,
            authors=list(entry.authors),
            year=entry.publication_year,
            venue=entry.venue,
            method_summary=verified.verified_method_summary.summary,
            research_problem=verified.original_analysis.research_problem,
            primary_contribution=grounded_contrib[0] if grounded_contrib else None,
            primary_limitation=grounded_lim[0] if grounded_lim else None,
            additional_contributions=[item for item in contributions if not grounded_contrib or item.statement_key != grounded_contrib[0].statement_key],
            additional_limitations=[item for item in limitations if not grounded_lim or item.statement_key != grounded_lim[0].statement_key],
            key_findings=list(linked.findings),
            verified_evidence_count=sum(1 for item in evidence.values() if item.status in {VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_SUPPORTED}),
            grounded_statement_count=linked.linking_statistics.grounded_statements,
            evidence_confidence_summary=(sum(item.confidence for item in [*contributions, *limitations, *linked.findings]) / max(1, len([*contributions, *limitations, *linked.findings]))),
            contribution_availability=(
                "VERIFIED_CONTRIBUTION" if grounded_contrib else self._missing_availability(entry, "contribution")
            ),
            limitation_availability=(
                "VERIFIED_LIMITATION" if grounded_lim else self._missing_availability(entry, "limitation")
            ),
            source_url=entry.source_url,
            sources=list(entry.sources),
            full_text_status=entry.full_text_status,
        )

    @staticmethod
    def _timeline(entry, linked):
        contributions = [item for item in linked.contributions if item.is_evidence_grounded]
        findings = [item for item in linked.findings if item.is_evidence_grounded]
        limitations = [item for item in linked.limitations if item.is_evidence_grounded and item.statement_basis in {LimitationBasis.AUTHOR_STATED, LimitationBasis.EVIDENCE_BOUND_OBSERVATION}]
        contribution = contributions[0] if contributions else None
        contribution_kind = "contribution"
        if contribution is None and findings:
            contribution = findings[0]
            contribution_kind = "key_finding"
        limitation = limitations[0] if limitations else None
        return LiteratureTimelineEntry(
            citation_number=entry.citation_number,
            paper_id=entry.paper_id,
            year=entry.publication_year,
            year_unknown=entry.publication_year is None,
            authors_short=entry.first_author or "",
            short_title=entry.title[:120],
            primary_contribution=contribution.text if contribution else None,
            contribution_kind=contribution_kind,
            contribution_status=contribution.support_status if contribution else None,
            contribution_evidence_keys=list(contribution.supporting_evidence_keys) if contribution else [],
            primary_limitation=limitation.text if limitation else None,
            limitation_status=limitation.support_status if limitation else StatementSupportStatus.UNMAPPED,
            limitation_basis=limitation.statement_basis if limitation else None,
            limitation_evidence_keys=list(limitation.supporting_evidence_keys) if limitation else [],
            source_url=entry.source_url,
            doi=entry.doi,
            arxiv_id=entry.arxiv_id,
            semantic_scholar_id=entry.semantic_scholar_id,
            openalex_id=entry.openalex_id,
            sources=list(entry.sources),
            full_text_status=entry.full_text_status,
            contribution_availability=(
                "VERIFIED_CONTRIBUTION"
                if contribution and contribution_kind == "contribution"
                else "VERIFIED_KEY_FINDING"
                if contribution
                else SurveyEvidenceDataBuilder._missing_availability(entry, "contribution")
            ),
            limitation_availability=(
                "VERIFIED_LIMITATION"
                if limitation
                else SurveyEvidenceDataBuilder._missing_availability(entry, "limitation")
            ),
        )

    @staticmethod
    def _missing_availability(entry: CitationEntry, kind: str) -> str:
        """Explain a missing claim without silently converting absence into evidence."""

        if entry.full_text_status != "available":
            return "FULL_TEXT_UNAVAILABLE"
        if kind == "limitation":
            return "AUTHOR_LIMITATION_NOT_LOCATED"
        return "AUTHOR_CONTRIBUTION_NOT_LOCATED"

    @staticmethod
    def _readiness(entries):
        total = len(entries)
        with_contribution = sum(item.primary_contribution is not None for item in entries)
        with_limitation = sum(item.primary_limitation is not None for item in entries)
        return FishboneReadinessAssessment(
            total_core_entries=total,
            entries_with_grounded_contribution=with_contribution,
            entries_with_grounded_limitation=with_limitation,
            entries_missing_contribution=total - with_contribution,
            entries_missing_limitation=total - with_limitation,
            year_coverage=sorted({item.year for item in entries if item.year is not None}),
            ready=total > 0 and with_contribution == total,
        )


class CitationRegistry:
    """Assign stable citation numbers from canonical paper metadata."""

    def build(self, papers: Sequence[PaperCandidate], final_relevance: Mapping[UUID, FinalRelevanceAssessment] | None = None) -> list[CitationEntry]:
        candidates = []
        for paper in papers:
            assessment = final_relevance.get(paper.id) if final_relevance else None
            selected = final_relevance is None or (
                assessment is not None
                and
                assessment.final_classification is FinalRelevanceClassification.CORE
                and assessment.selected_for_report
            )
            if not selected:
                continue
            candidates.append((paper, assessment))
        unique: dict[str, tuple[PaperCandidate, FinalRelevanceAssessment | None]] = {}
        for paper, assessment in candidates:
            unique.setdefault(self.canonical_identifier(paper), (paper, assessment))
        candidates = list(unique.values())
        candidates.sort(key=lambda pair: self._sort_key(pair[0]))
        entries = [self._entry(index, paper, assessment) for index, (paper, assessment) in enumerate(candidates, 1)]
        self._validate(entries)
        return entries

    @staticmethod
    def _sort_key(paper):
        first = paper.authors[0].normalized_name if paper.authors and paper.authors[0].normalized_name else (paper.authors[0].full_name if paper.authors else "")
        return (paper.publication_year is None, paper.publication_year or 0, first.casefold(), paper.normalized_title.casefold(), CitationRegistry.canonical_identifier(paper))

    @staticmethod
    def canonical_identifier(paper: PaperCandidate) -> str:
        for value in (paper.doi, paper.arxiv_id, paper.semantic_scholar_id, paper.openalex_id, paper.normalized_title):
            if value and str(value).strip():
                return str(value).strip().casefold()
        return str(paper.id)

    @classmethod
    def _entry(cls, number, paper, assessment):
        authors = [author.full_name for author in paper.authors]
        return CitationEntry(
            citation_number=number,
            paper_id=paper.id,
            canonical_identifier=cls.canonical_identifier(paper),
            title=paper.title,
            authors=authors,
            first_author=authors[0] if authors else None,
            publication_year=paper.publication_year,
            venue=paper.venue,
            doi=paper.doi,
            arxiv_id=paper.arxiv_id,
            semantic_scholar_id=paper.semantic_scholar_id,
            openalex_id=paper.openalex_id,
            source_url=paper.landing_page_url or paper.pdf_url,
            sources=[source.value for source in paper.sources],
            full_text_status=paper.full_text_status.value,
            final_relevance=assessment.final_classification.value if assessment else None,
            selected_for_report=bool(assessment.selected_for_report) if assessment else True,
        )

    @staticmethod
    def _validate(entries):
        numbers = [entry.citation_number for entry in entries]
        identifiers = [entry.canonical_identifier for entry in entries]
        if len(numbers) != len(set(numbers)) or numbers != list(range(1, len(numbers) + 1)):
            raise CitationRegistryError("citation numbers must be unique and contiguous")
        if len(identifiers) != len(set(identifiers)):
            raise CitationRegistryError("canonical paper identifiers must be unique")


def citation_token(number: int, locator: SourceLocator | None = None) -> str:
    """Create a citation token using only a verified SourceLocator."""

    token = f"[{number}]"
    if locator is not None and locator.page_start is not None:
        token = f"[{number}, p.{locator.page_start}]"
    return token


def citation_group(numbers: Sequence[int]) -> str:
    """Create a stable compact citation group."""

    return "[" + ",".join(str(number) for number in sorted(set(numbers))) + "]"


def public_citation_refs(
    statement_keys: Sequence[str],
    evidence_ledger: Sequence[EvidenceLedgerEntry],
) -> list[str]:
    """Rebuild one compact public citation from statement-to-evidence links.

    The writer only supplies internal statement keys.  This function follows
    those keys through the verified evidence ledger, whose citation numbers
    originate in :class:`CitationRegistry`.  A single unambiguous source page
    retains ``[n, p.x]``; multiple pieces of evidence from one paper collapse
    to ``[n]`` and multiple papers use the shared ``citation_group`` policy.
    """

    selected = set(statement_keys)
    pairs = [
        (item.citation_number, item.page)
        for item in evidence_ledger
        if item.statement_key in selected
    ]
    return public_citation_refs_from_pairs(pairs)


def public_citation_refs_from_pairs(pairs: Sequence[tuple[int, int | None]]) -> list[str]:
    """Apply the shared public citation grouping policy to verified locators."""

    if not pairs:
        return []
    pages_by_number: dict[int, set[int]] = {}
    for number, page in pairs:
        if page is not None:
            pages_by_number.setdefault(number, set()).add(page)
        else:
            pages_by_number.setdefault(number, set())
    numbers = sorted(pages_by_number)
    if len(numbers) != 1:
        return [citation_group(numbers)]
    number = numbers[0]
    pages = pages_by_number[number]
    if len(pages) == 1:
        return [citation_token(number, type("Locator", (), {"page_start": next(iter(pages))})())]
    return [citation_group(numbers)]


@dataclass(frozen=True)
class PublicReportCitationIndex:
    """Public citation numbers reconstructed from verified legacy report citations."""

    numbers_by_evidence: Mapping[UUID, int]
    pages_by_evidence: Mapping[UUID, int | None]
    titles_by_number: Mapping[int, str | None]

    def refs_for_evidence_ids(self, evidence_ids: Sequence[UUID]) -> list[str]:
        """Return one compact public citation token for a claim's evidence."""

        return public_citation_refs_from_pairs([
            (self.numbers_by_evidence[item], self.pages_by_evidence.get(item))
            for item in dict.fromkeys(evidence_ids)
            if item in self.numbers_by_evidence
        ])


def build_public_report_citation_index(citations: Sequence[object]) -> PublicReportCitationIndex:
    """Build a stable public index from already-verified legacy citations.

    This is a compatibility bridge for ``ResearchReport`` export.  It follows
    its verified evidence ID to paper identity and source locator, then assigns
    the same compact citation-number presentation used by ``CitationRegistry``.
    No UUID is returned as public content.
    """

    papers: dict[UUID, tuple[str | None, UUID]] = {}
    for citation in citations:
        paper_id = citation.paper_id
        papers.setdefault(paper_id, (citation.paper_title, paper_id))
    ordered = sorted(
        papers.items(),
        key=lambda item: ((item[1][0] or "").casefold(), str(item[0])),
    )
    number_by_paper = {paper_id: index for index, (paper_id, _) in enumerate(ordered, 1)}
    titles = {number_by_paper[paper_id]: title for paper_id, (title, _) in papers.items()}
    return PublicReportCitationIndex(
        numbers_by_evidence={item.evidence_id: number_by_paper[item.paper_id] for item in citations},
        pages_by_evidence={item.evidence_id: item.locator.page_start for item in citations},
        titles_by_number=titles,
    )


def resolve_statement_locators(
    statement: EvidenceLinkedStatement,
    verified_result: VerifiedPaperAnalysisResult,
) -> list[SourceLocator]:
    """Resolve linked evidence keys to their real, stable source locators."""

    by_key = {
        str(item.evidence.id): item.evidence.locator
        for item in verified_result.verification.verified_evidence
    }
    return [deepcopy(by_key[key]) for key in statement.supporting_evidence_keys if key in by_key]
