"""Evidence-grounded taxonomy and comparison data foundation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from enum import Enum
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paperpilot.analysis import (
    EvidenceLinkedPaperAnalysis,
    EvidenceLinkedStatement,
    StatementKind,
    StatementSupportStatus,
    StructuredLLMProtocol,
)
from paperpilot.domain import PaperCandidate
from paperpilot.relevance import FinalRelevanceClassification, ReportMode
from paperpilot.verification import VerificationStatus, VerifiedPaperAnalysisResult

from .citations import CitationEntry, SurveyEvidenceData, citation_token
from .exceptions import ReportSchemaValidationError, ReportWriterError


class TaxonomyError(ValueError):
    """Raised when taxonomy output cannot be safely validated."""


class SupportLevel(str, Enum):
    SINGLE_PAPER = "single_paper"
    MULTI_PAPER = "multi_paper"
    UNCLASSIFIED = "unclassified"


class MethodFamily(BaseModel):
    """One evidence-grounded semantic method family."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family_key: str
    name: str
    description: str
    common_mechanism: str
    advantages: list[str]
    limitations: list[str]
    member_citation_numbers: list[int]
    source_statement_keys: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    support_level: SupportLevel

    def public_dict(self) -> dict:
        return self.model_dump(exclude={"source_statement_keys"}, mode="json")


class MethodFamilyAssignment(BaseModel):
    """Primary and optional secondary family for one selected CORE paper."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_number: int = Field(ge=1)
    primary_method_family: str
    secondary_method_families: list[str] = Field(default_factory=list)
    assignment_status: str = "assigned"

    @model_validator(mode="after")
    def validate_primary_unique(self) -> "MethodFamilyAssignment":
        if self.primary_method_family in self.secondary_method_families:
            raise ValueError("primary family cannot also be secondary")
        return self

    def public_dict(self) -> dict:
        return self.model_dump(exclude={"source_statement_keys"}, mode="json")


class MethodFamilyDraft(BaseModel):
    """Small LLM output contract for one family; no citation strings allowed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1_500)
    common_mechanism: str = Field(min_length=1, max_length=800)
    advantages: list[str] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=12)
    member_citation_numbers: list[int] = Field(max_length=50)
    source_statement_keys: list[str] = Field(max_length=50)


class MethodFamilyAssignmentDraft(BaseModel):
    """Small LLM output contract for a paper-to-family assignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_number: int = Field(ge=1)
    primary_family_name: str | None = None
    secondary_family_names: list[str] = Field(default_factory=list)


class TaxonomyLLMOutput(BaseModel):
    """The only structured payload accepted from one taxonomy LLM call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    families: list[MethodFamilyDraft] = Field(max_length=50)
    assignments: list[MethodFamilyAssignmentDraft] = Field(max_length=50)
    summary: str = Field(default="", max_length=2_000)


class TaxonomyAssessment(BaseModel):
    """Validated taxonomy plus safe degradation diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    taxonomy: list[MethodFamily]
    assignments: list[MethodFamilyAssignment]
    warnings: list[str]
    available: bool
    summary: str = ""

    @property
    def family_count(self) -> int:
        return len(self.taxonomy)


# Public name used by the analysis contract; the assessment is the validated
# method taxonomy plus its assignments and diagnostics.
MethodTaxonomy = TaxonomyAssessment


class TaxonomyContextBudget(BaseModel):
    """Bound one taxonomy prompt per research task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_core_papers: int = Field(default=10, ge=1, le=50)
    max_statements_per_paper: int = Field(default=12, ge=1, le=50)
    max_context_characters: int = Field(default=20_000, ge=1_000, le=100_000)


class TaxonomyContext(BaseModel):
    """Compact selected-CORE context for semantic grouping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    papers: list[dict]
    allowed_statement_keys: list[str]
    context_text: str
    truncated: bool
    warnings: list[str]


class TaxonomyContextBuilder:
    """Build only grounded contribution/finding context for taxonomy."""

    def __init__(self, budget: TaxonomyContextBudget | None = None) -> None:
        self.budget = budget or TaxonomyContextBudget()

    def build(self, data: SurveyEvidenceData) -> TaxonomyContext:
        # Accept the already compact SurveyReportContext as an integration
        # convenience without importing it (avoids a reporting-cycle import).
        if hasattr(data, "allowed_statement_keys") and hasattr(data, "core_papers") and not hasattr(data, "core_paper_profiles"):
            raw_papers = list(getattr(data, "core_papers"))
            papers = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in raw_papers[: self.budget.max_core_papers]]
            allowed = list(getattr(data, "allowed_statement_keys"))
            payload = json.dumps(papers, ensure_ascii=False, separators=(",", ":"))
            truncated = len(papers) < len(raw_papers)
            if len(payload) > self.budget.max_context_characters:
                payload = payload[: self.budget.max_context_characters - 1] + "…"
                truncated = True
            return TaxonomyContext(papers=papers, allowed_statement_keys=allowed, context_text=payload, truncated=truncated, warnings=["TAXONOMY_CONTEXT_TRUNCATED"] if truncated else [])
        profiles = data.core_paper_profiles[: self.budget.max_core_papers]
        allowed: list[str] = []
        papers: list[dict] = []
        for profile in profiles:
            statements = [
                item
                for item in [*([profile.primary_contribution] if profile.primary_contribution else []), *profile.additional_contributions, *profile.key_findings]
                if item.is_evidence_grounded
                and item.support_status in {StatementSupportStatus.SUPPORTED, StatementSupportStatus.PARTIALLY_SUPPORTED}
            ][: self.budget.max_statements_per_paper]
            for statement in statements:
                allowed.append(statement.statement_key)
            papers.append({
                "citation_number": profile.citation_number,
                "title": profile.title,
                "year": profile.year,
                "method_summary": profile.method_summary,
                "method_summary_status": "grounded" if statements else "descriptive_unverified_context",
                "grounded_statements": [
                    {"statement_key": item.statement_key, "kind": item.kind.value, "text": item.text}
                    for item in statements
                ],
            })
        warnings: list[str] = []
        payload = json.dumps(papers, ensure_ascii=False, separators=(",", ":"))
        truncated = len(profiles) < len(data.core_paper_profiles)
        if len(payload) > self.budget.max_context_characters:
            payload = payload[: self.budget.max_context_characters - 1] + "…"
            truncated = True
        if truncated:
            warnings.append("TAXONOMY_CONTEXT_TRUNCATED")
        return TaxonomyContext(
            papers=papers,
            allowed_statement_keys=list(dict.fromkeys(allowed)),
            context_text=payload,
            truncated=truncated,
            warnings=warnings,
        )


class TaxonomyValidator:
    """Reject hallucinated papers, keys, families, and duplicate primary assignments."""

    def validate(self, output: TaxonomyLLMOutput, context: TaxonomyContext) -> TaxonomyAssessment:
        citation_numbers = {int(paper["citation_number"]) for paper in context.papers}
        allowed_keys = set(context.allowed_statement_keys)
        family_by_name = {item.name.strip(): item for item in output.families}
        if len(family_by_name) != len(output.families):
            raise TaxonomyError("duplicate taxonomy family names")
        for family in output.families:
            if not family.member_citation_numbers:
                raise TaxonomyError("empty family support")
            if not set(family.member_citation_numbers).issubset(citation_numbers):
                raise TaxonomyError("unknown or non-core citation")
            if not set(family.source_statement_keys).issubset(allowed_keys):
                raise TaxonomyError("unknown taxonomy statement key")
            if not family.source_statement_keys:
                raise TaxonomyError("family has no grounded source")
        assigned: dict[int, MethodFamilyAssignment] = {}
        seen_assignments: set[int] = set()
        for item in output.assignments:
            if item.citation_number not in citation_numbers:
                raise TaxonomyError("assignment references non-core paper")
            if item.citation_number in seen_assignments:
                raise TaxonomyError("duplicate primary family assignment")
            seen_assignments.add(item.citation_number)
            if item.primary_family_name is None:
                assigned[item.citation_number] = MethodFamilyAssignment(
                    citation_number=item.citation_number,
                    primary_method_family="UNCLASSIFIED",
                    assignment_status="unclassified",
                )
                continue
            if item.primary_family_name.strip() not in family_by_name:
                raise TaxonomyError("assignment references unknown family")
            if any(name.strip() not in family_by_name for name in item.secondary_family_names):
                raise TaxonomyError("assignment references unknown secondary family")
        families = [self._family(item, citation_numbers) for item in output.families]
        family_keys = {family.name: family.family_key for family in families}
        for item in output.assignments:
            if item.primary_family_name is None:
                continue
            primary = item.primary_family_name.strip()
            assigned[item.citation_number] = MethodFamilyAssignment(
                citation_number=item.citation_number,
                primary_method_family=family_keys[primary],
                secondary_method_families=[family_keys[name.strip()] for name in item.secondary_family_names],
            )
        assignment_models: list[MethodFamilyAssignment] = []
        warnings: list[str] = []
        for number in sorted(citation_numbers):
            item = assigned.get(number)
            if item is None:
                item = MethodFamilyAssignment(citation_number=number, primary_method_family="UNCLASSIFIED", assignment_status="unclassified")
            if item.primary_method_family == "UNCLASSIFIED":
                warnings.append("TAXONOMY_UNCLASSIFIED_CORE")
            assignment_models.append(item)
        return TaxonomyAssessment(taxonomy=families, assignments=assignment_models, warnings=list(dict.fromkeys(warnings)), available=bool(families))

    @staticmethod
    def _family(draft: MethodFamilyDraft, citation_numbers: set[int]) -> MethodFamily:
        members = sorted(set(draft.member_citation_numbers))
        key = hashlib.sha256(f"{draft.name.strip().casefold()}|{','.join(map(str, members))}".encode()).hexdigest()[:16]
        return MethodFamily(
            family_key=key,
            name=draft.name.strip(),
            description=draft.description.strip(),
            common_mechanism=draft.common_mechanism.strip(),
            advantages=list(dict.fromkeys(draft.advantages)),
            limitations=list(dict.fromkeys(draft.limitations)),
            member_citation_numbers=members,
            source_statement_keys=list(dict.fromkeys(draft.source_statement_keys)),
            confidence=0.8 if len(members) > 1 else 0.6,
            support_level=SupportLevel.MULTI_PAPER if len(members) > 1 else SupportLevel.SINGLE_PAPER,
        )


class TaxonomyService:
    """Run at most one taxonomy LLM call and degrade safely on failure."""

    def __init__(self, llm: StructuredLLMProtocol | None = None, validator: TaxonomyValidator | None = None) -> None:
        self.llm = llm
        self.validator = validator or TaxonomyValidator()

    def generate(self, context: TaxonomyContext, report_mode: ReportMode, *, telemetry=None) -> TaxonomyAssessment:
        if report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW or not context.papers:
            return TaxonomyAssessment(taxonomy=[], assignments=[], warnings=["TAXONOMY_UNAVAILABLE"], available=False, summary="")
        if self.llm is None:
            return TaxonomyAssessment(taxonomy=[], assignments=[], warnings=["TAXONOMY_GENERATION_FAILED"], available=False, summary="")
        prompt = (
            "Return only TaxonomyLLMOutput JSON. Group selected CORE papers by "
            "shared technical mechanism. Use only supplied citation numbers and "
            "grounded statement keys. Never invent papers or evidence. "
            "When the supplied context contains Chinese, write taxonomy names, "
            "descriptions, mechanisms, advantages, limitations, and summary in "
            "Simplified Chinese while preserving technical proper nouns.\n"
            f"Context: {context.context_text}"
        )
        started = telemetry.llm_started("taxonomy", 1, len(prompt)) if telemetry is not None else None
        try:
            output = self.llm.generate_structured(
                system_prompt="You perform conservative technical method-family grouping.",
                user_prompt=prompt,
                response_model=TaxonomyLLMOutput,
            )
            parsed = output if isinstance(output, TaxonomyLLMOutput) else TaxonomyLLMOutput.model_validate(output)
            assessment = self.validator.validate(parsed, context)
            result = assessment.model_copy(update={"summary": parsed.summary.strip()})
            if telemetry is not None:
                telemetry.llm_succeeded("taxonomy", 1, started)
            return result
        except Exception as error:
            if telemetry is not None:
                telemetry.llm_failed("taxonomy", 1, started, error)
            return TaxonomyAssessment(taxonomy=[], assignments=[], warnings=["TAXONOMY_GENERATION_FAILED"], available=False, summary="")


class DeterministicTaxonomyBuilder:
    """Offline/demo grouping based only on grounded statement token overlap."""

    _STOP = {"the", "and", "with", "for", "from", "using", "into", "based", "method"}

    def build(self, context: TaxonomyContext) -> TaxonomyAssessment:
        groups: list[dict] = []
        assignments: list[MethodFamilyAssignment] = []
        for paper in context.papers:
            statements = paper.get("grounded_statements", [])
            if not statements:
                assignments.append(MethodFamilyAssignment(citation_number=paper["citation_number"], primary_method_family="UNCLASSIFIED", assignment_status="unclassified"))
                continue
            tokens = self._tokens(" ".join(item["text"] for item in statements))
            target = next((group for group in groups if self._overlap(tokens, group["tokens"]) >= 0.35), None)
            if target is None:
                target = {"name": f"Method family {len(groups) + 1}", "tokens": tokens, "members": [], "keys": []}
                groups.append(target)
            target["members"].append(paper["citation_number"])
            target["keys"].extend(item["statement_key"] for item in statements)
            assignments.append(MethodFamilyAssignment(citation_number=paper["citation_number"], primary_method_family="UNCLASSIFIED", assignment_status="unclassified"))
        families: list[MethodFamily] = []
        for group in groups:
            members = sorted(set(group["members"]))
            key = hashlib.sha256(f"{group['name'].casefold()}|{','.join(map(str, members))}".encode()).hexdigest()[:16]
            families.append(MethodFamily(
                family_key=key,
                name=group["name"],
                description="Deterministic grouping of papers sharing grounded mechanism terms.",
                common_mechanism=" ".join(sorted(group["tokens"])),
                advantages=[], limitations=[], member_citation_numbers=members,
                source_statement_keys=list(dict.fromkeys(group["keys"])), confidence=0.5,
                support_level=SupportLevel.MULTI_PAPER if len(members) > 1 else SupportLevel.SINGLE_PAPER,
            ))
        by_citation = {number: family.family_key for family in families for number in family.member_citation_numbers}
        assignments = [MethodFamilyAssignment(citation_number=item.citation_number, primary_method_family=by_citation.get(item.citation_number, "UNCLASSIFIED"), assignment_status="assigned" if item.citation_number in by_citation else "unclassified") for item in assignments]
        warnings = ["TAXONOMY_UNCLASSIFIED_CORE"] if any(item.primary_method_family == "UNCLASSIFIED" for item in assignments) else []
        return TaxonomyAssessment(taxonomy=families, assignments=assignments, warnings=warnings, available=bool(families))

    @classmethod
    def _tokens(cls, text):
        return {token for token in re.findall(r"[\w]+", text.casefold()) if token not in cls._STOP}

    @staticmethod
    def _overlap(left, right):
        return len(left & right) / max(1, min(len(left), len(right)))


class GroundingStatus(str, Enum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    DESCRIPTIVE_UNVERIFIED = "descriptive_unverified"
    MISSING = "missing"


class ComparisonColumn(str, Enum):
    CITATION = "citation"
    YEAR = "year"
    METHOD_FAMILY = "method_family"
    RESEARCH_FOCUS = "research_focus"
    PRIMARY_CONTRIBUTION = "primary_contribution"
    KEY_FINDINGS = "key_findings"
    PRIMARY_LIMITATION = "primary_limitation"
    EVIDENCE_COVERAGE = "evidence_coverage"
    DATASET = "dataset"
    METRIC = "metric"
    REPORTED_RESULT = "reported_result"


class ComparisonCell(BaseModel):
    """One comparison value with explicit provenance status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str | float | int | list[str] | None
    value_type: str
    grounding_status: GroundingStatus
    source_statement_keys: list[str] = Field(default_factory=list)
    citation_tokens: list[str] = Field(default_factory=list)
    notes: str | None = None

    def public_dict(self) -> dict:
        return self.model_dump(exclude={"source_statement_keys"}, mode="json")


class ComparisonRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_number: int = Field(ge=1)
    cells: dict[ComparisonColumn, ComparisonCell]

    def public_dict(self) -> dict:
        return {"citation_number": self.citation_number, "cells": {key.value: value.public_dict() for key, value in self.cells.items()}}


class ComparisonMatrixData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    columns: list[ComparisonColumn]
    rows: list[ComparisonRow]
    warnings: list[str]

    def public_dict(self) -> dict:
        return {"columns": [item.value for item in self.columns], "rows": [item.public_dict() for item in self.rows], "warnings": list(self.warnings)}


class ComparabilityLevel(str, Enum):
    DIRECTLY_COMPARABLE = "directly_comparable"
    PARTIALLY_COMPARABLE = "partially_comparable"
    NOT_DIRECTLY_COMPARABLE = "not_directly_comparable"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class ComparabilityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: ComparabilityLevel
    shared_datasets: list[str]
    shared_metrics: list[str]
    same_evaluation_scope: bool | None
    same_unit: bool | None
    reasons: list[str]


class CrossPaperComparisonFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_family_counts: dict[str, int]
    papers_by_year: dict[str, int]
    papers_with_verified_limitation: int
    papers_without_verified_limitation: int
    dataset_usage: dict[str, int]
    metric_usage: dict[str, int]
    verified_finding_coverage: float = Field(ge=0.0, le=1.0)
    conflicted_finding_count: int = Field(ge=0)


class TaxonomyEvidenceCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    family_count: int = Field(ge=0)
    assigned_core_count: int = Field(ge=0)
    unclassified_core_count: int = Field(ge=0)
    families_with_multi_paper_support: int = Field(ge=0)
    families_with_single_paper_support: int = Field(ge=0)
    grounded_statement_coverage: float = Field(ge=0.0, le=1.0)
    ready_for_survey: bool


class SurveyAnalysisData(BaseModel):
    """Analysis layer separate from SurveyEvidenceData."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    taxonomy: TaxonomyAssessment
    comparison_matrix: ComparisonMatrixData
    comparison_facts: CrossPaperComparisonFacts
    comparability: ComparabilityAssessment
    taxonomy_coverage: TaxonomyEvidenceCoverage
    warnings: list[str]

    def public_dict(self) -> dict:
        return {
            "taxonomy": {
                "taxonomy": [item.public_dict() for item in self.taxonomy.taxonomy],
                "assignments": [item.public_dict() for item in self.taxonomy.assignments],
                "warnings": list(self.taxonomy.warnings),
                "available": self.taxonomy.available,
            },
            "comparison_matrix": self.comparison_matrix.public_dict(),
            "comparison_facts": self.comparison_facts.model_dump(mode="json"),
            "comparability": self.comparability.model_dump(mode="json"),
            "taxonomy_coverage": self.taxonomy_coverage.model_dump(mode="json"),
            "warnings": list(self.warnings),
        }


class ComparisonDataBuilder:
    """Build matrix, comparability, and cross-paper facts without an LLM."""

    def build(
        self,
        evidence_data: SurveyEvidenceData,
        papers: Sequence[PaperCandidate],
        linked_analyses: Mapping[str, EvidenceLinkedPaperAnalysis],
        verified_results: Mapping[str, VerifiedPaperAnalysisResult],
        taxonomy: TaxonomyAssessment,
    ) -> SurveyAnalysisData:
        papers_by_id = {str(paper.id): paper for paper in papers}
        profiles = {profile.citation_number: profile for profile in evidence_data.core_paper_profiles}
        assignment_by_citation = {item.citation_number: item for item in taxonomy.assignments}
        statement_tokens: dict[str, list[str]] = defaultdict(list)
        for ledger in evidence_data.evidence_ledger:
            if ledger.statement_key:
                token = citation_token(ledger.citation_number)
                if token not in statement_tokens[ledger.statement_key]:
                    statement_tokens[ledger.statement_key].append(token)
        rows: list[ComparisonRow] = []
        dataset_counts: Counter[str] = Counter()
        metric_counts: Counter[str] = Counter()
        years: Counter[str] = Counter()
        findings_total = findings_grounded = conflicts = 0
        for entry in evidence_data.citation_registry:
            profile = profiles.get(entry.citation_number)
            if profile is None:
                continue
            paper = papers_by_id.get(str(entry.paper_id))
            verified = verified_results.get(str(paper.id)) if paper else None
            linked = linked_analyses.get(str(paper.id)) if paper else None
            cells: dict[ComparisonColumn, ComparisonCell] = {
                ComparisonColumn.CITATION: ComparisonCell(value=entry.citation_number, value_type="citation", grounding_status=GroundingStatus.VERIFIED, citation_tokens=[f"[{entry.citation_number}]"]),
                ComparisonColumn.YEAR: ComparisonCell(value=entry.publication_year, value_type="metadata", grounding_status=GroundingStatus.VERIFIED if entry.publication_year else GroundingStatus.MISSING),
                ComparisonColumn.METHOD_FAMILY: ComparisonCell(value=assignment_by_citation.get(entry.citation_number, MethodFamilyAssignment(citation_number=entry.citation_number, primary_method_family="UNCLASSIFIED")).primary_method_family, value_type="taxonomy", grounding_status=GroundingStatus.VERIFIED if entry.citation_number in assignment_by_citation else GroundingStatus.MISSING),
                ComparisonColumn.RESEARCH_FOCUS: ComparisonCell(value=profile.research_problem, value_type="structured", grounding_status=GroundingStatus.DESCRIPTIVE_UNVERIFIED, notes="No per-statement evidence association retained."),
                ComparisonColumn.PRIMARY_CONTRIBUTION: self._statement_cell(profile.primary_contribution, tokens=statement_tokens),
                ComparisonColumn.PRIMARY_LIMITATION: self._statement_cell(profile.primary_limitation, missing_note="NO_VERIFIED_LIMITATION", tokens=statement_tokens),
                ComparisonColumn.KEY_FINDINGS: self._findings_cell(linked, statement_tokens),
                ComparisonColumn.EVIDENCE_COVERAGE: ComparisonCell(value=profile.verified_evidence_count, value_type="count", grounding_status=GroundingStatus.VERIFIED),
            }
            if verified is not None:
                experiment = verified.verified_experiment_summary
                dataset_status = GroundingStatus.DESCRIPTIVE_UNVERIFIED if experiment.datasets else GroundingStatus.MISSING
                metric_status = GroundingStatus.DESCRIPTIVE_UNVERIFIED if experiment.metrics else GroundingStatus.MISSING
                cells[ComparisonColumn.DATASET] = ComparisonCell(value=list(experiment.datasets) or None, value_type="structured", grounding_status=dataset_status)
                cells[ComparisonColumn.METRIC] = ComparisonCell(value=list(experiment.metrics.keys()) or None, value_type="structured", grounding_status=metric_status)
                cells[ComparisonColumn.REPORTED_RESULT] = ComparisonCell(value=list(experiment.findings) or None, value_type="structured", grounding_status=GroundingStatus.DESCRIPTIVE_UNVERIFIED if experiment.findings else GroundingStatus.MISSING)
                dataset_counts.update(experiment.datasets)
                metric_counts.update(experiment.metrics.keys())
            rows.append(ComparisonRow(citation_number=entry.citation_number, cells=cells))
            if entry.publication_year:
                years[str(entry.publication_year)] += 1
            finding_items = [item for item in (linked.findings if linked else [])]
            findings_total += len(finding_items)
            findings_grounded += sum(item.is_evidence_grounded for item in finding_items)
            conflicts += sum(item.support_status is StatementSupportStatus.CONFLICTED for item in finding_items)
        base_columns = [
            ComparisonColumn.CITATION, ComparisonColumn.YEAR, ComparisonColumn.METHOD_FAMILY,
            ComparisonColumn.RESEARCH_FOCUS, ComparisonColumn.PRIMARY_CONTRIBUTION,
            ComparisonColumn.KEY_FINDINGS, ComparisonColumn.PRIMARY_LIMITATION,
            ComparisonColumn.EVIDENCE_COVERAGE,
        ]
        optional_columns = [ComparisonColumn.DATASET, ComparisonColumn.METRIC, ComparisonColumn.REPORTED_RESULT]
        columns = base_columns + [
            column for column in optional_columns
            if any(row.cells.get(column) and row.cells[column].grounding_status is not GroundingStatus.MISSING for row in rows)
        ]
        matrix = ComparisonMatrixData(columns=columns, rows=rows, warnings=[])
        comparability = self._comparability(rows)
        facts = CrossPaperComparisonFacts(
            method_family_counts=dict(Counter(item.primary_method_family for item in taxonomy.assignments)),
            papers_by_year=dict(years),
            papers_with_verified_limitation=sum(profile.primary_limitation is not None for profile in profiles.values()),
            papers_without_verified_limitation=sum(profile.primary_limitation is None for profile in profiles.values()),
            dataset_usage=dict(dataset_counts), metric_usage=dict(metric_counts),
            verified_finding_coverage=findings_grounded / max(1, findings_total),
            conflicted_finding_count=conflicts,
        )
        coverage = TaxonomyEvidenceCoverage(
            family_count=len(taxonomy.taxonomy),
            assigned_core_count=sum(item.primary_method_family != "UNCLASSIFIED" for item in taxonomy.assignments),
            unclassified_core_count=sum(item.primary_method_family == "UNCLASSIFIED" for item in taxonomy.assignments),
            families_with_multi_paper_support=sum(item.support_level is SupportLevel.MULTI_PAPER for item in taxonomy.taxonomy),
            families_with_single_paper_support=sum(item.support_level is SupportLevel.SINGLE_PAPER for item in taxonomy.taxonomy),
            grounded_statement_coverage=findings_grounded / max(1, findings_total),
            ready_for_survey=bool(rows),
        )
        return SurveyAnalysisData(taxonomy=taxonomy, comparison_matrix=matrix, comparison_facts=facts, comparability=comparability, taxonomy_coverage=coverage, warnings=list(taxonomy.warnings))

    @staticmethod
    def _statement_cell(statement: EvidenceLinkedStatement | None, missing_note: str = "", tokens: Mapping[str, list[str]] | None = None) -> ComparisonCell:
        if statement is None:
            return ComparisonCell(value=None, value_type="statement", grounding_status=GroundingStatus.MISSING, notes=missing_note or None)
        status = GroundingStatus.VERIFIED if statement.support_status is StatementSupportStatus.SUPPORTED else GroundingStatus.PARTIAL if statement.support_status is StatementSupportStatus.PARTIALLY_SUPPORTED else GroundingStatus.MISSING
        return ComparisonCell(value=statement.text, value_type="statement", grounding_status=status, source_statement_keys=[statement.statement_key], citation_tokens=list((tokens or {}).get(statement.statement_key, [])), notes=missing_note or None)

    @classmethod
    def _findings_cell(cls, linked: EvidenceLinkedPaperAnalysis | None, tokens: Mapping[str, list[str]] | None = None) -> ComparisonCell:
        if linked is None:
            return ComparisonCell(value=None, value_type="finding", grounding_status=GroundingStatus.MISSING)
        findings = [item for item in linked.findings if item.support_status in {StatementSupportStatus.SUPPORTED, StatementSupportStatus.PARTIALLY_SUPPORTED}]
        if not findings:
            return ComparisonCell(value=None, value_type="finding", grounding_status=GroundingStatus.MISSING)
        status = GroundingStatus.VERIFIED if all(item.support_status is StatementSupportStatus.SUPPORTED for item in findings) else GroundingStatus.PARTIAL
        citation_tokens = [token for item in findings for token in (tokens or {}).get(item.statement_key, [])]
        return ComparisonCell(value=[item.text for item in findings], value_type="finding", grounding_status=status, source_statement_keys=[item.statement_key for item in findings], citation_tokens=list(dict.fromkeys(citation_tokens)))

    @staticmethod
    def _comparability(rows):
        datasets = [set(row.cells.get(ComparisonColumn.DATASET, ComparisonCell(value=None, value_type="", grounding_status=GroundingStatus.MISSING)).value or []) for row in rows]
        metrics = [set(row.cells.get(ComparisonColumn.METRIC, ComparisonCell(value=None, value_type="", grounding_status=GroundingStatus.MISSING)).value or []) for row in rows]
        shared_datasets = sorted(set.intersection(*datasets)) if datasets and all(datasets) else []
        shared_metrics = sorted(set.intersection(*metrics)) if metrics and all(metrics) else []
        available_datasets = any(datasets)
        available_metrics = any(metrics)
        if len(rows) < 2 or not available_datasets or not available_metrics:
            level = ComparabilityLevel.INSUFFICIENT_INFORMATION
        elif shared_datasets and shared_metrics:
            level = ComparabilityLevel.DIRECTLY_COMPARABLE
        elif shared_metrics:
            level = ComparabilityLevel.PARTIALLY_COMPARABLE
        else:
            level = ComparabilityLevel.NOT_DIRECTLY_COMPARABLE
        return ComparabilityAssessment(level=level, shared_datasets=shared_datasets, shared_metrics=shared_metrics, same_evaluation_scope=None, same_unit=None, reasons=[level.value])


class SurveyAnalysisDataBuilder:
    """Compose the bounded taxonomy and deterministic comparison artifacts."""

    def __init__(self, taxonomy_service: TaxonomyService | None = None, context_builder: TaxonomyContextBuilder | None = None, comparison_builder: ComparisonDataBuilder | None = None) -> None:
        self.context_builder = context_builder or TaxonomyContextBuilder()
        self.taxonomy_service = taxonomy_service or TaxonomyService()
        self.comparison_builder = comparison_builder or ComparisonDataBuilder()

    def build(self, data: SurveyEvidenceData, papers: Sequence[PaperCandidate], linked_analyses: Mapping[str, EvidenceLinkedPaperAnalysis], verified_results: Mapping[str, VerifiedPaperAnalysisResult], report_mode: ReportMode, *, deterministic: bool = False, telemetry=None) -> SurveyAnalysisData:
        context = self.context_builder.build(data)
        taxonomy_started = telemetry.substage_started("taxonomy") if telemetry is not None else None
        try:
            taxonomy = DeterministicTaxonomyBuilder().build(context) if deterministic else self.taxonomy_service.generate(context, report_mode, telemetry=telemetry)
        except Exception as error:
            if telemetry is not None:
                telemetry.substage_failed("taxonomy", taxonomy_started, error)
            raise
        if telemetry is not None:
            telemetry.update_input_counts(taxonomy_family_count=len(taxonomy.taxonomy))
            telemetry.substage_completed("taxonomy", taxonomy_started)
        comparison_started = telemetry.substage_started("comparison") if telemetry is not None else None
        try:
            result = self.comparison_builder.build(data, papers, linked_analyses, verified_results, taxonomy)
        except Exception as error:
            if telemetry is not None:
                telemetry.substage_failed("comparison", comparison_started, error)
            raise
        if telemetry is not None:
            telemetry.update_input_counts(comparison_row_count=len(result.comparison_matrix.rows))
            telemetry.substage_completed("comparison", comparison_started)
        return result
