"""Survey report contracts and citation-safe deterministic assembly."""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Literal, Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paperpilot.analysis import (
    EvidenceLinkedPaperAnalysis,
    EvidenceLinkedStatement,
    LimitationBasis,
    StatementKind,
    StatementSupportStatus,
    StructuredLLMProtocol,
)
from paperpilot.orchestration import ResearchState
from paperpilot.relevance import ReportMode
from paperpilot.relevance.language import normalize_query_language

from .citations import (
    CitationEntry,
    EvidenceLedgerEntry,
    FishboneReadinessAssessment,
    LiteratureTimelineEntry,
    ReferenceEntry,
    public_citation_refs,
    SurveyEvidenceData,
    citation_token,
)
from .exceptions import ReportSchemaValidationError, ReportWriterError


class SurveyClaimType(str, Enum):
    BACKGROUND = "background"
    METHOD = "method"
    FINDING = "finding"
    COMPARISON = "comparison"
    LIMITATION = "limitation"
    TREND = "trend"
    CONCLUSION = "conclusion"


class ClaimCertainty(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StatementReference(BaseModel):
    """Public statement reference consumed by the citation-safe writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement_key: str
    citation_number: int = Field(ge=1)
    statement_kind: StatementKind
    text: str
    support_status: StatementSupportStatus
    confidence: float = Field(ge=0.0, le=1.0)
    citation_tokens: list[str]
    is_evidence_grounded: bool
    limitation_basis: LimitationBasis | None = None


class SurveyContextBudget(BaseModel):
    """Deterministic limits applied before context is sent to the LLM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_core_papers: int = Field(default=10, ge=1, le=50)
    max_statements_per_paper: int = Field(default=20, ge=1, le=100)
    max_evidence_quotes_per_statement: int = Field(default=3, ge=1, le=10)
    max_conflicted_statements: int = Field(default=10, ge=0, le=100)
    max_context_characters: int = Field(default=30_000, ge=1_000, le=200_000)


class SurveyReportContext(BaseModel):
    """Safe writer context with public metadata and internal statement keys."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    research_question: str
    query_language: Literal["en", "zh"] = "en"
    report_mode: ReportMode
    scope_summary: str
    retrieval_statistics: dict[str, int]
    core_papers: list[dict]
    references: list[ReferenceEntry]
    grounded_statements: list[StatementReference]
    conflicted_statements: list[StatementReference]
    evidence_limitations: list[str]
    timeline_summary: list[dict]
    fishbone_readiness: FishboneReadinessAssessment
    allowed_statement_keys: list[str]
    warnings: list[str]
    context_text: str
    truncated: bool

    def public_dict(self) -> dict:
        """Return the safe context view used in the writer prompt."""

        payload = self.model_dump(mode="json")
        return payload


class LiteratureMethodFacts(BaseModel):
    """Deterministic retrieval and relevance facts for narrative context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    planned_queries: int = Field(default=0, ge=0)
    executed_queries: int = Field(default=0, ge=0)
    raw_candidates: int = Field(default=0, ge=0)
    deduplicated_candidates: int = Field(default=0, ge=0)
    preliminary_core: int = Field(default=0, ge=0)
    possible_adjacent: int = Field(default=0, ge=0)
    metadata_rejected: int = Field(default=0, ge=0)
    papers_read: int = Field(default=0, ge=0)
    final_core: int = Field(default=0, ge=0)
    final_adjacent: int = Field(default=0, ge=0)
    final_rejected: int = Field(default=0, ge=0)
    unassessable: int = Field(default=0, ge=0)
    selected_core: int = Field(default=0, ge=0)

    @classmethod
    def from_state(cls, state: ResearchState) -> "LiteratureMethodFacts":
        retrieval = state.get("retrieval_audit")
        final = state.get("final_relevance_audit")
        return cls(
            planned_queries=getattr(retrieval, "planned_query_count", 0),
            executed_queries=getattr(retrieval, "executed_query_count", 0),
            raw_candidates=getattr(retrieval, "raw_candidate_count", 0),
            deduplicated_candidates=getattr(retrieval, "deduplicated_candidate_count", 0),
            preliminary_core=getattr(retrieval, "preliminary_core_count", 0),
            possible_adjacent=getattr(retrieval, "possible_adjacent_count", 0),
            metadata_rejected=getattr(retrieval, "metadata_rejected_count", 0),
            papers_read=getattr(final, "papers_successfully_read", len(state.get("analyses", {}))),
            final_core=getattr(final, "final_core_count", 0),
            final_adjacent=getattr(final, "final_adjacent_count", 0),
            final_rejected=getattr(final, "final_rejected_count", 0),
            unassessable=getattr(final, "papers_unassessable", 0),
            selected_core=getattr(final, "selected_core_count", 0),
        )


class SurveyClaimDraft(BaseModel):
    """Structured claim produced by the LLM before citation reconstruction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    source_statement_keys: list[str] = Field(default_factory=list)
    claim_type: SurveyClaimType
    certainty: ClaimCertainty = ClaimCertainty.MEDIUM

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("survey claim text must not be empty")
        return value


class SurveyNarrativeDraft(BaseModel):
    """Bounded narrative draft; references and evidence appendix are assembled in code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    abstract: str
    introduction: str
    literature_method_summary: str
    evidence_summary: str
    limitations: str
    conclusion: str
    claims: list[SurveyClaimDraft]


class SurveyClaim(BaseModel):
    """Final claim with deterministic citation tokens."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    claim_type: SurveyClaimType
    certainty: ClaimCertainty
    source_statement_keys: list[str]
    citation_tokens: list[str]


class SurveyParagraph(BaseModel):
    """A rendered paragraph with auditable claim and citation references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    claim_keys: list[str] = Field(default_factory=list)
    citation_refs: list[str] = Field(default_factory=list)


class SurveyFigureSlot(BaseModel):
    """Semantic figure placeholder; rendering is deferred to a later stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    figure_id: str
    figure_type: str
    caption: str
    data_source: str
    timeline_entry_count: int = Field(ge=0)
    render_status: str = "SLOT_ONLY"


class SurveyTable(BaseModel):
    """Semantic table slot backed by deterministic comparison data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    table_id: str
    table_type: str
    caption: str
    data_source: str
    row_count: int = Field(ge=0)


class FutureDirectionKind(str, Enum):
    LITERATURE_SUPPORTED = "literature_supported"
    SYNTHESIZED_INFERENCE = "synthesized_inference"


class SurveyFutureDirection(BaseModel):
    """A future-work direction with explicit evidence basis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    kind: FutureDirectionKind
    source_statement_keys: list[str] = Field(default_factory=list)
    citation_tokens: list[str] = Field(default_factory=list)


class SurveySection(BaseModel):
    """Ordered survey section containing auditable paragraphs and claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    section_id: str
    number: str
    title: str
    section_type: str
    paragraphs: list[SurveyParagraph] = Field(default_factory=list)
    claims: list[SurveyClaim] = Field(default_factory=list)
    tables: list[SurveyTable] = Field(default_factory=list)
    figure_slots: list[SurveyFigureSlot] = Field(default_factory=list)
    subsections: list["SurveySection"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


SurveySection.model_rebuild()


class SurveyReport(BaseModel):
    """Structured survey report assembled from narrative plus deterministic data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: dict[str, str | int | float | None]
    query_language: Literal["en", "zh"] = "en"
    title: str
    abstract: str
    keywords: list[str] = Field(default_factory=list, max_length=8)
    introduction: str
    literature_method: str
    evidence_summary: str
    limitations: str
    conclusion: str
    claims: list[SurveyClaim]
    references: list[ReferenceEntry]
    evidence_appendix: list[EvidenceLedgerEntry]
    literature_timeline: list[LiteratureTimelineEntry]
    report_mode: ReportMode
    warnings: list[str]
    sections: list[SurveySection] = Field(default_factory=list)
    figures: list[SurveyFigureSlot] = Field(default_factory=list)
    tables: list[SurveyTable] = Field(default_factory=list)
    core_paper_profiles: list[dict] = Field(default_factory=list)
    taxonomy_summary: dict = Field(default_factory=dict)
    comparison_facts: dict = Field(default_factory=dict)
    comparison_matrix: dict = Field(default_factory=dict)
    future_directions: list[SurveyFutureDirection] = Field(default_factory=list)

    def public_dict(self) -> dict:
        """Return a user-facing representation without internal UUIDs."""

        payload = self.model_dump(mode="json")
        return _remove_internal_fields(payload)


_PUBLIC_INTERNAL_FIELDS = frozenset({
    "paper_id", "statement_key", "source_statement_key", "source_statement_keys", "claim_keys",
    "evidence_id", "evidence_ids", "evidence_key", "evidence_key_internal",
    "supporting_evidence_keys", "contradicting_evidence_keys",
    "unsupported_evidence_keys", "contribution_evidence_keys",
    "limitation_evidence_keys", "execution_id", "task_id", "report_mode",
    "render_status", "method_family_counts", "query_language",
})


def _remove_internal_fields(value):
    """Remove model-only linkage fields from a public serialization."""

    if isinstance(value, dict):
        return {
            key: _remove_internal_fields(item)
            for key, item in value.items()
            if key.casefold() not in _PUBLIC_INTERNAL_FIELDS
        }
    if isinstance(value, list):
        return [_remove_internal_fields(item) for item in value]
    return value


class SurveyReportContextBuilder:
    """Build bounded public context from SurveyEvidenceData."""

    def __init__(self, budget: SurveyContextBudget | None = None) -> None:
        self.budget = budget or SurveyContextBudget()

    def build(
        self,
        question: str,
        data: SurveyEvidenceData,
        report_mode: ReportMode,
        facts: LiteratureMethodFacts | None = None,
        *,
        query_language: str | None = None,
    ) -> SurveyReportContext:
        facts = facts or LiteratureMethodFacts()
        papers = list(data.core_paper_profiles[: self.budget.max_core_papers])
        allowed: list[str] = []
        grounded: list[StatementReference] = []
        conflicted: list[StatementReference] = []
        for profile in papers:
            statements = [
                *([profile.primary_contribution] if profile.primary_contribution else []),
                *([profile.primary_limitation] if profile.primary_limitation else []),
                *profile.additional_contributions,
                *profile.additional_limitations,
                *profile.key_findings,
            ]
            statements = sorted(
                statements,
                key=lambda item: (
                    item.support_status not in {StatementSupportStatus.SUPPORTED, StatementSupportStatus.PARTIALLY_SUPPORTED},
                    -item.confidence,
                    item.statement_key,
                ),
            )[: self.budget.max_statements_per_paper]
            for statement in statements:
                if statement.support_status in {
                    StatementSupportStatus.UNMAPPED,
                    StatementSupportStatus.UNSUPPORTED,
                }:
                    continue
                allowed.append(statement.statement_key)
                reference = self._reference(statement, profile.citation_number, data.evidence_ledger, self.budget.max_evidence_quotes_per_statement)
                if statement.support_status is StatementSupportStatus.CONFLICTED:
                    if len(conflicted) < self.budget.max_conflicted_statements:
                        conflicted.append(reference)
                elif statement.is_evidence_grounded and statement.support_status in {StatementSupportStatus.SUPPORTED, StatementSupportStatus.PARTIALLY_SUPPORTED}:
                    grounded.append(reference)
        warnings = list(data.warnings)
        evidence_limitations = list(data.warnings)
        if any(profile.limitation_availability == "NO_VERIFIED_LIMITATION" for profile in papers):
            evidence_limitations.append("NO_VERIFIED_LIMITATION")
        truncated = len(papers) < len(data.core_paper_profiles)
        if truncated:
            warnings.append("SURVEY_CONTEXT_TRUNCATED")
        context_text = json.dumps(
            {
                "scope": question,
                "report_mode": report_mode.value,
                "core_papers": [item.public_dict() for item in papers],
                "references": [item.model_dump(mode="json") for item in data.references if item.citation_number <= len(papers)],
                "grounded_statements": [item.model_dump(mode="json") for item in grounded],
                "conflicted_statements": [item.model_dump(mode="json") for item in conflicted],
                "literature_method_facts": facts.model_dump(mode="json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(context_text) > self.budget.max_context_characters:
            context_text = context_text[: self.budget.max_context_characters - 1] + "…"
            truncated = True
            warnings.append("SURVEY_CONTEXT_TRUNCATED")
        return SurveyReportContext(
            research_question=question.strip(),
            query_language=normalize_query_language(query_language, question=question),
            report_mode=report_mode,
            scope_summary=facts.model_dump_json(),
            retrieval_statistics=facts.model_dump(),
            core_papers=[item.public_dict() for item in papers],
            references=[item for item in data.references if item.citation_number <= len(papers)],
            grounded_statements=grounded,
            conflicted_statements=conflicted,
            evidence_limitations=list(dict.fromkeys(evidence_limitations)),
            timeline_summary=[item.public_dict() for item in data.literature_timeline if item.citation_number <= len(papers)],
            fishbone_readiness=data.fishbone_readiness,
            allowed_statement_keys=list(dict.fromkeys(allowed)),
            warnings=list(dict.fromkeys(warnings)),
            context_text=context_text,
            truncated=truncated,
        )

    @staticmethod
    def _reference(statement: EvidenceLinkedStatement, citation_number: int, ledger: Sequence[EvidenceLedgerEntry], max_quotes: int) -> StatementReference:
        tokens = [
            citation_token(item.citation_number, type("Locator", (), {"page_start": item.page})() if item.page else None)
            for item in ledger
            if item.statement_key == statement.statement_key
        ][:max_quotes]
        if not tokens:
            tokens = [citation_token(citation_number)]
        return StatementReference(
            statement_key=statement.statement_key,
            citation_number=citation_number,
            statement_kind=statement.kind,
            text=statement.text,
            support_status=statement.support_status,
            confidence=statement.confidence,
            citation_tokens=tokens,
            is_evidence_grounded=statement.is_evidence_grounded,
            limitation_basis=statement.statement_basis,
        )


class CitationSafeSurveyWriter:
    """Generate only narrative drafts; citations are reconstructed after the LLM call."""

    def __init__(self, llm: StructuredLLMProtocol) -> None:
        self.llm = llm

    def write(self, context: SurveyReportContext) -> SurveyNarrativeDraft:
        prompt = (
            "Return only SurveyNarrativeDraft JSON. Use source_statement_keys "
            "for every factual claim. Never create citation numbers, UUIDs, "
            "evidence IDs, paper IDs, or unsupported source keys. "
            f"Report mode: {context.report_mode.value}.\n"
            f"Allowed statement keys: {json.dumps(context.allowed_statement_keys)}\n"
            f"Context: {context.context_text}"
        )
        try:
            output = self.llm.generate_structured(
                system_prompt="You write a conservative evidence-grounded survey narrative.",
                user_prompt=prompt,
                response_model=SurveyNarrativeDraft,
            )
            draft = output if isinstance(output, SurveyNarrativeDraft) else SurveyNarrativeDraft.model_validate(output)
        except Exception as error:
            raise ReportWriterError("survey narrative generation failed") from error
        unknown = {
            key
            for claim in draft.claims
            for key in claim.source_statement_keys
            if key not in set(context.allowed_statement_keys)
        }
        if unknown:
            raise ReportSchemaValidationError("UNKNOWN_REPORT_STATEMENT_KEY")
        SurveyPublicContentValidator().validate_narrative_draft(draft)
        return draft


class SurveyPublicContentValidator:
    """Reject internal linkage data and invalid citation tokens before export."""

    _UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)
    _INTERNAL_NAME = re.compile(
        r"\b(?:allowed_statement_keys|source_statement_keys|statement_key|"
        r"paper_id|claim_keys|evidence_id|evidence_key(?:_internal)?|"
        r"execution_id|task_id|method_family_counts|report_mode|"
        r"chunk_id|chunk_[a-z0-9_-]+|evid_[a-z0-9_-]+)\b",
        re.I,
    )
    _INTERNAL_STATUS = re.compile(r"\b(?:TAXONOMY_[A-Z_]+|SLOT_ONLY)\b")
    _INTERNAL_STAGE = re.compile(
        r"(?:\bStage\s+[A-D]\b|阶段\s*[A-DＡ-Ｄ]\s*草稿)", re.I
    )
    _LOCAL_PATH = re.compile(
        r"(?:\b[A-Za-z]:\\|(?:^|\s)/(?:Users|home|tmp|var|app|workspace)/)",
        re.I,
    )
    _CITATION = re.compile(r"\[(\d+(?:\s*,\s*(?:\d+|p\.\s*\d+))*)\]")

    @classmethod
    def contains_internal_identifier(cls, value: str) -> bool:
        """Return whether reader-visible prose contains a private linkage token."""

        return bool(
            cls._UUID.search(value)
            or cls._INTERNAL_NAME.search(value)
            or cls._INTERNAL_STATUS.search(value)
            or cls._INTERNAL_STAGE.search(value)
            or cls._LOCAL_PATH.search(value)
        )

    def validate(self, report: SurveyReport) -> None:
        self._validate_language_contract(report)
        payload = report.public_dict()
        self._validate_public_payload(payload, {item.citation_number for item in report.references})

    @staticmethod
    def _validate_language_contract(report: SurveyReport) -> None:
        """Keep Chinese presentation deterministic even with sparse evidence."""

        if report.query_language != "zh":
            return
        public_labels = [report.title, report.abstract, *(item.title for item in report.sections)]
        if any(not re.search(r"[\u3400-\u9fff]", value) for value in public_labels):
            raise ReportSchemaValidationError("SURVEY_OUTPUT_LANGUAGE_MISMATCH")

    def validate_stage_drafts(self, drafts) -> None:
        """Fail assembly when LLM prose contains a raw internal identifier."""

        values: list[str] = []
        for draft in drafts:
            values.append(draft.title)
            values.extend(item.text for item in draft.paragraphs)
            values.extend(item.text for item in draft.claims)
            values.extend(item.text for item in draft.future_directions)
        self._validate_texts(values, set())

    def validate_narrative_draft(self, draft: SurveyNarrativeDraft) -> None:
        values = [draft.title, draft.abstract, draft.introduction, draft.literature_method_summary, draft.evidence_summary, draft.limitations, draft.conclusion]
        values.extend(item.text for item in draft.claims)
        self._validate_texts(values, set())

    def _validate_public_payload(
        self,
        value,
        citation_numbers: set[int],
        *,
        field_path: str = "report",
        literal_source_quote: bool = False,
    ) -> None:
        if isinstance(value, dict):
            if any(key.casefold() in _PUBLIC_INTERNAL_FIELDS for key in value):
                raise ReportSchemaValidationError("PUBLIC_INTERNAL_ID_LEAK")
            for key, item in value.items():
                self._validate_public_payload(
                    item,
                    citation_numbers,
                    field_path=f"{field_path}.{key}",
                    # EvidenceLedgerEntry.quote is a literal source excerpt.
                    # Bracketed numbers in it belong to the source paper's own
                    # bibliography, not to this report's public registry.
                    literal_source_quote=literal_source_quote or key == "quote",
                )
            return
        if isinstance(value, list):
            for item in value:
                self._validate_public_payload(
                    item,
                    citation_numbers,
                    field_path=f"{field_path}[]",
                    literal_source_quote=literal_source_quote,
                )
            return
        if isinstance(value, str):
            self._validate_texts(
                [value],
                set() if literal_source_quote else citation_numbers,
                field_path=field_path,
            )

    def _validate_texts(
        self,
        values: Sequence[str],
        citation_numbers: set[int],
        *,
        field_path: str = "report",
    ) -> None:
        for value in values:
            if self._UUID.search(value) or self._LOCAL_PATH.search(value):
                raise self._validation_error("PUBLIC_INTERNAL_ID_LEAK", field_path)
            if (
                self._INTERNAL_NAME.search(value)
                or self._INTERNAL_STATUS.search(value)
                or self._INTERNAL_STAGE.search(value)
            ):
                raise self._validation_error("PUBLIC_INTERNAL_SCHEMA_LEAK", field_path)
            for match in self._CITATION.finditer(value):
                for part in match.group(1).split(","):
                    part = part.strip()
                    if part.startswith("p."):
                        continue
                    if citation_numbers and int(part) not in citation_numbers:
                        raise self._validation_error("UNKNOWN_PUBLIC_CITATION", field_path)

    @staticmethod
    def _validation_error(rule: str, field_path: str) -> ReportSchemaValidationError:
        """Attach a safe structural field label for private telemetry only."""

        error = ReportSchemaValidationError(rule)
        error.validation_rule = rule
        error.validation_field = field_path
        return error


class PublicSurveyCitationValidator(SurveyPublicContentValidator):
    """Final public-export guard for citation validity and ID-leak prevention."""


class SurveyReportVerifier:
    """Deterministically verify claim bindings and reconstructed citations."""

    def verify(self, report: SurveyReport, context: SurveyReportContext) -> SurveyReport:
        allowed = set(context.allowed_statement_keys)
        for claim in report.claims:
            if claim.claim_type is not SurveyClaimType.BACKGROUND and not claim.source_statement_keys:
                raise ReportSchemaValidationError("UNSUPPORTED_SURVEY_CLAIM")
            if any(key not in allowed for key in claim.source_statement_keys):
                raise ReportSchemaValidationError("UNKNOWN_REPORT_STATEMENT_KEY")
            if len(claim.source_statement_keys) != len(set(claim.source_statement_keys)):
                raise ReportSchemaValidationError("DUPLICATE_STATEMENT_KEY")
            if claim.source_statement_keys and not claim.citation_tokens:
                raise ReportSchemaValidationError("MISSING_CITATION_TOKEN")
        expected_refs = {item.citation_number for item in context.references}
        actual_refs = {item.citation_number for item in report.references}
        if expected_refs != actual_refs:
            raise ReportSchemaValidationError("REFERENCE_INTEGRITY_ERROR")
        PublicSurveyCitationValidator().validate(report)
        return report.model_copy(deep=True)


class SurveyReportAssembler:
    """Combine narrative draft and deterministic survey data."""

    def assemble(
        self,
        draft: SurveyNarrativeDraft,
        data: SurveyEvidenceData,
        report_mode: ReportMode,
        facts: LiteratureMethodFacts | None = None,
    ) -> SurveyReport:
        SurveyPublicContentValidator().validate_narrative_draft(draft)
        references = list(data.references)
        allowed = {row.statement_key for row in data.evidence_ledger}
        claims: list[SurveyClaim] = []
        for claim in draft.claims:
            keys = list(dict.fromkeys(claim.source_statement_keys))
            if claim.claim_type is not SurveyClaimType.BACKGROUND and not keys:
                raise ReportSchemaValidationError("UNSUPPORTED_SURVEY_CLAIM")
            if any(key not in allowed for key in keys):
                raise ReportSchemaValidationError("UNKNOWN_REPORT_STATEMENT_KEY")
            claims.append(SurveyClaim(
                text=claim.text,
                claim_type=claim.claim_type,
                certainty=claim.certainty,
                source_statement_keys=keys,
                citation_tokens=public_citation_refs(keys, data.evidence_ledger),
            ))
        if report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW:
            warnings = [*data.warnings, "EVIDENCE_LIMITED_REVIEW: conclusions are bounded by verified coverage."]
        else:
            warnings = list(data.warnings)
        metadata = {
            "report_mode": report_mode.value,
            "selected_core_papers": len(data.core_paper_profiles),
            "verified_evidence": len(data.evidence_ledger),
        }
        if facts is not None:
            metadata.update({key: value for key, value in facts.model_dump().items() if isinstance(value, (int, float))})
        return SurveyReport(
            metadata=metadata,
            title=draft.title,
            abstract=draft.abstract,
            introduction=draft.introduction,
            literature_method=draft.literature_method_summary,
            evidence_summary=draft.evidence_summary,
            limitations=draft.limitations,
            conclusion=draft.conclusion,
            claims=claims,
            references=references,
            evidence_appendix=list(data.evidence_ledger),
            literature_timeline=list(data.literature_timeline),
            report_mode=report_mode,
            warnings=list(dict.fromkeys(warnings)),
        )
