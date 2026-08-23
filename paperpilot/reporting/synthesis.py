"""Bounded, evidence-grounded full survey synthesis.

This layer writes small section drafts and deterministically assembles the
report structure, citations, references, tables, and figure slots.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paperpilot.relevance import ReportMode

from .analysis_data import SurveyAnalysisData
from .citations import SurveyEvidenceData, public_citation_refs
from .exceptions import ReportSchemaValidationError, ReportWriterError
from .survey import (
    ClaimCertainty,
    LiteratureMethodFacts,
    StatementReference,
    SurveyClaim,
    SurveyClaimDraft,
    SurveyClaimType,
    SurveyFigureSlot,
    FutureDirectionKind,
    SurveyFutureDirection,
    SurveyParagraph,
    SurveyReport,
    SurveyReportContext,
    SurveySection,
    SurveyTable,
    SurveyPublicContentValidator,
)
from paperpilot.analysis import (
    AnalysisSchemaValidationError,
    StructuredLLMProtocol,
)


class SynthesisStage(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _uses_chinese(question: str) -> bool:
    return bool(_CJK_RE.search(question))


class ReportDensity(str, Enum):
    SHORT = "short"
    STANDARD = "standard"
    EXTENDED = "extended"


def choose_report_density(selected_core_count: int, family_count: int, grounded_statement_count: int) -> ReportDensity:
    """Select safe writing density from evidence volume, never user verbosity."""

    score = selected_core_count + family_count + grounded_statement_count // 4
    if score < 5:
        return ReportDensity.SHORT
    if score < 14:
        return ReportDensity.STANDARD
    return ReportDensity.EXTENDED


class SynthesisStageBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_context_characters: int = Field(default=50_000, ge=1_000, le=50_000)
    max_output_characters: int = Field(default=8_000, ge=500, le=30_000)


class SurveySynthesisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_llm_calls: int = Field(default=4, ge=1, le=4)
    schema_retry_attempts: int = Field(default=1, ge=0, le=2)
    stage_budget: SynthesisStageBudget = Field(default_factory=SynthesisStageBudget)


class CrossPaperClaimPolicy:
    """Constrain consensus language to independent paper support."""

    _CONSENSUS = re.compile(r"\b(majority|most studies|consensus|widely accepted|普遍|多数研究|共识)\b", re.I)

    @classmethod
    def validate(cls, claim: SurveyClaimDraft, citation_numbers: set[int]) -> None:
        if claim.claim_type in {SurveyClaimType.COMPARISON, SurveyClaimType.TREND} and len(citation_numbers) < 2:
            raise ReportSchemaValidationError("INSUFFICIENT_CROSS_PAPER_SUPPORT")
        if cls._CONSENSUS.search(claim.text) and len(citation_numbers) < 2:
            raise ReportSchemaValidationError("UNSUPPORTED_CONSENSUS_LANGUAGE")


class SurveyParagraphDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=4_000)
    section_type: str | None = Field(default=None, max_length=80)
    source_statement_keys: list[str] = Field(default_factory=list, max_length=20)


class SurveyFutureDirectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=1_500)
    kind: FutureDirectionKind
    source_statement_keys: list[str] = Field(default_factory=list, max_length=20)


class SurveyStageDraft(BaseModel):
    """Small structured response for exactly one synthesis stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: SynthesisStage
    title: str = Field(min_length=1, max_length=240)
    paragraphs: list[SurveyParagraphDraft] = Field(default_factory=list, max_length=20)
    claims: list[SurveyClaimDraft] = Field(default_factory=list, max_length=30)
    future_directions: list[SurveyFutureDirectionDraft] = Field(default_factory=list, max_length=10)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class SurveySynthesisWriter:
    """Perform at most four small structured calls, one per synthesis stage."""

    def __init__(self, llm: StructuredLLMProtocol, config: SurveySynthesisConfig | None = None) -> None:
        self.llm = llm
        self.config = config or SurveySynthesisConfig()
        self.calls = 0

    def write(self, context: SurveyReportContext, analysis_data: SurveyAnalysisData, *, telemetry=None) -> list[SurveyStageDraft]:
        stages = [SynthesisStage.A, SynthesisStage.B, SynthesisStage.C, SynthesisStage.D]
        results: list[SurveyStageDraft] = []
        for stage in stages[: self.config.max_llm_calls]:
            prompt = self._prompt(stage, context, analysis_data)
            chinese = context.query_language == "zh"
            language_rule = (
                "Write all narrative prose and the report title in Simplified Chinese. "
                "Preserve paper titles, method names, datasets, metrics, abbreviations, "
                "and verbatim quotations in their original language."
                if chinese
                else "Write all narrative prose in the language of the research question."
            )
            draft: SurveyStageDraft | None = None
            for attempt in range(self.config.schema_retry_attempts + 1):
                retry_instruction = (
                    ""
                    if attempt == 0
                    else (
                        "\nThe previous response failed schema validation. Return a minimal "
                        "valid object with exactly these top-level fields: stage, title, "
                        "paragraphs, claims, future_directions, warnings. Set stage to "
                        f"{stage.value}. Use empty lists for claims, future_directions, or "
                        "warnings when uncertain. Do not add any other fields."
                    )
                )
                call_index = self.calls + 1
                started = (
                    telemetry.llm_started(
                        f"synthesis_{stage.value.lower()}",
                        call_index,
                        len(prompt) + len(retry_instruction),
                    )
                    if telemetry is not None
                    else None
                )
                try:
                    output = self.llm.generate_structured(
                        system_prompt=(
                            "Write one concise academic survey section. Use only supplied "
                            "evidence keys; never invent facts or citations. JSON field names, "
                            "stage labels, linkage keys, and uppercase status codes are control "
                            "metadata: never mention them in any reader-visible text value. "
                            + language_rule
                            + retry_instruction
                        ),
                        user_prompt=prompt,
                        response_model=SurveyStageDraft,
                    )
                    draft = (
                        output
                        if isinstance(output, SurveyStageDraft)
                        else SurveyStageDraft.model_validate(output)
                    )
                except AnalysisSchemaValidationError as error:
                    self.calls += 1
                    if telemetry is not None:
                        telemetry.llm_failed(
                            f"synthesis_{stage.value.lower()}",
                            call_index,
                            started,
                            error,
                        )
                    if attempt < self.config.schema_retry_attempts:
                        continue
                    draft = self._fallback_draft(stage, context, analysis_data)
                    break
                except Exception as error:
                    self.calls += 1
                    if telemetry is not None:
                        telemetry.llm_failed(
                            f"synthesis_{stage.value.lower()}",
                            call_index,
                            started,
                            error,
                        )
                    raise ReportWriterError(
                        f"survey synthesis stage {stage.value} failed"
                    ) from error
                self.calls += 1
                if telemetry is not None:
                    telemetry.llm_succeeded(
                        f"synthesis_{stage.value.lower()}", call_index, started
                    )
                break
            if draft is None:
                raise ReportWriterError(
                    f"survey synthesis stage {stage.value} produced no draft"
                )
            if draft.stage is not stage:
                raise ReportSchemaValidationError("SYNTHESIS_STAGE_MISMATCH")
            narrative = " ".join(
                [draft.title]
                + [item.text for item in draft.paragraphs]
                + [item.text for item in draft.claims]
                + [item.text for item in draft.future_directions]
            )
            if chinese and not _CJK_RE.search(narrative):
                raise ReportSchemaValidationError("SURVEY_OUTPUT_LANGUAGE_MISMATCH")
            output_size = sum(len(item.text) for item in draft.paragraphs) + sum(len(item.text) for item in draft.claims)
            if output_size > self.config.stage_budget.max_output_characters:
                raise ReportSchemaValidationError("SYNTHESIS_OUTPUT_TOO_LARGE")
            results.append(draft)
        return results

    @staticmethod
    def _fallback_draft(
        stage: SynthesisStage,
        context: SurveyReportContext,
        analysis_data: SurveyAnalysisData,
    ) -> SurveyStageDraft:
        """Return evidence-bounded prose when provider JSON stays invalid."""

        chinese = context.query_language == "zh"
        layouts = (
            SurveySynthesisAssembler._SECTION_LAYOUT_ZH
            if chinese
            else SurveySynthesisAssembler._SECTION_LAYOUT
        )
        paper_count = len(context.references)
        row_count = len(analysis_data.comparison_matrix.rows)
        family_count = len(analysis_data.taxonomy.taxonomy)
        if chinese:
            templates = {
                "introduction": f"本报告围绕调研问题整理 {paper_count} 篇已验证核心文献，所有结论均限制在当前证据范围内。",
                "literature_method": "系统对自动检索与人工补充文献执行统一的去重、全文解析、证据提取和引用校验。",
                "background": f"当前证据语料包含 {paper_count} 篇核心文献，可用于形成受证据约束的研究背景概述。",
                "taxonomy": f"确定性分析识别出 {family_count} 个方法类别；分类仅反映当前纳入文献。",
                "progress": "研究进展按已验证文献和方法类别组织，不对缺失证据作推断。",
                "comparison": f"证据对比矩阵包含 {row_count} 个文献条目，仅展示已验证或明确缺失的字段。",
                "discussion": "跨论文讨论仅概括当前证据中可核验的共同点与差异。",
                "challenges": "现有问题仅依据已验证的局限性证据陈述，未获得支持的内容保持为空。",
                "future": "当现有证据不足以支持具体方向时，本报告不生成推测性的未来研究结论。",
                "conclusion": f"本报告基于 {paper_count} 篇核心文献形成证据受限结论，引用与证据附录可供复核。",
            }
            title = "证据受限的确定性综述段落"
            warning = "部分综述段落因模型返回格式异常而使用了确定性证据摘要。"
        else:
            templates = {
                "introduction": f"This report organizes {paper_count} verified core papers and limits conclusions to the available evidence.",
                "literature_method": "Automatic and manually supplied papers undergo the same deduplication, full-text parsing, evidence extraction, and citation checks.",
                "background": f"The verified corpus contains {paper_count} core papers for an evidence-bounded background overview.",
                "taxonomy": f"Deterministic analysis identified {family_count} method families within the included literature.",
                "progress": "Research progress is organized only from verified papers and method families, without inferring missing evidence.",
                "comparison": f"The evidence comparison matrix contains {row_count} literature rows and preserves explicitly missing fields.",
                "discussion": "Cross-paper discussion is limited to verifiable similarities and differences in the current evidence.",
                "challenges": "Challenges are reported only when supported by verified limitation evidence.",
                "future": "No speculative future direction is generated when the present evidence is insufficient.",
                "conclusion": f"The report provides evidence-bounded conclusions from {paper_count} core papers with auditable references.",
            }
            title = "Deterministic evidence-bounded survey section"
            warning = "Some survey prose used a deterministic evidence summary because the model returned an invalid structure."
        return SurveyStageDraft(
            stage=stage,
            title=title,
            paragraphs=[
                SurveyParagraphDraft(text=templates[section_type], section_type=section_type)
                for _, _, section_type in layouts[stage]
            ],
            warnings=[warning],
        )
    def _prompt(self, stage: SynthesisStage, context: SurveyReportContext, analysis_data: SurveyAnalysisData) -> str:
        sections = {
            SynthesisStage.A: "front matter, introduction, and literature retrieval method",
            SynthesisStage.B: "background, existing taxonomy, and method-family progress",
            SynthesisStage.C: "experimental comparison and cross-paper discussion",
            SynthesisStage.D: "evidence-grounded challenges, future directions, and conclusion",
        }
        layouts = SurveySynthesisAssembler._SECTION_LAYOUT_ZH if context.query_language == "zh" else SurveySynthesisAssembler._SECTION_LAYOUT
        taxonomy = analysis_data.taxonomy.public_dict() if hasattr(analysis_data.taxonomy, "public_dict") else analysis_data.taxonomy.model_dump(mode="json")
        taxonomy.pop("warnings", None)
        comparison = analysis_data.comparison_matrix.public_dict()
        comparison.pop("warnings", None)
        payload = {
            "question": context.research_question,
            "output_language": "zh-CN" if context.query_language == "zh" else "question-language",
            "preserve_source_language_for": ["paper_titles", "method_names", "datasets", "metrics", "abbreviations", "verbatim_quotes"],
            "evidence_link_keys": context.allowed_statement_keys,
            "taxonomy": taxonomy,
            "comparison": comparison,
            "human_readable_facts": self._human_readable_facts(context, analysis_data),
            "section_types": [item[2] for item in layouts[stage]],
            "writing_scope": sections[stage],
        }
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return (
            f"Return only SurveyStageDraft JSON for internal stage {stage.value}. Write {sections[stage]}. "
            "The draft title is only an internal stage label, never the final report title. "
            "Set each paragraph's section_type to one of the supplied section_types. "
            "Every factual claim must cite supplied source_statement_keys. Do not create papers, numbers, "
            "families, datasets, metrics, limitations, trends, or citations. A singleton family must be "
            "described as a single study; missing values remain missing. Never repeat any JSON field name, "
            "internal stage label, linkage key, or uppercase status code in prose.\n" + text[: self.config.stage_budget.max_context_characters]
        )

    @staticmethod
    def _human_readable_facts(context: SurveyReportContext, analysis_data: SurveyAnalysisData) -> list[str]:
        chinese = context.query_language == "zh"
        facts = analysis_data.comparison_facts
        result: list[str] = []
        for family, count in sorted(facts.method_family_counts.items()):
            result.append(
                f"方法族“{family}”包含 {count} 篇入选论文。"
                if chinese
                else f"Method family '{family}' contains {count} selected paper(s)."
            )
        result.append(
            f"{facts.papers_with_verified_limitation} 篇论文具有已验证的局限性证据，{facts.papers_without_verified_limitation} 篇暂无此类证据。"
            if chinese
            else f"{facts.papers_with_verified_limitation} paper(s) have verified limitation evidence; {facts.papers_without_verified_limitation} do not."
        )
        return result


class SurveySynthesisAssembler:
    """Deterministically combine stage drafts with immutable evidence data."""

    _GENERATED_CITATION = re.compile(
        r"\[(?:\d+|p\.\d+)(?:\s*,\s*(?:\d+|p\.\d+))*\]", re.I
    )

    _SECTION_LAYOUT = {
        SynthesisStage.A: [("1", "Introduction", "introduction"), ("2", "Literature Review Method", "literature_method")],
        SynthesisStage.B: [("3", "Background and Key Technologies", "background"), ("4", "Method Taxonomy", "taxonomy"), ("5", "Research Progress by Method Family", "progress")],
        SynthesisStage.C: [("6", "Experimental Comparison", "comparison"), ("7", "Cross-paper Discussion", "discussion")],
        SynthesisStage.D: [("8", "Challenges", "challenges"), ("9", "Future Directions", "future"), ("10", "Conclusion", "conclusion")],
    }
    _SECTION_LAYOUT_ZH = {
        SynthesisStage.A: [("1", "引言", "introduction"), ("2", "文献检索与筛选方法", "literature_method")],
        SynthesisStage.B: [("3", "研究背景与关键技术", "background"), ("4", "技术分类体系", "taxonomy"), ("5", "按方法族组织的研究进展", "progress")],
        SynthesisStage.C: [("6", "实验与性能对比", "comparison"), ("7", "跨论文综合比较与讨论", "discussion")],
        SynthesisStage.D: [("8", "现有问题与挑战", "challenges"), ("9", "未来研究方向", "future"), ("10", "结论", "conclusion")],
    }

    def assemble(self, drafts: Sequence[SurveyStageDraft], context: SurveyReportContext, evidence_data: SurveyEvidenceData, analysis_data: SurveyAnalysisData, facts: LiteratureMethodFacts | None = None) -> SurveyReport:
        # Exclude individual writer fragments that copied private linkage
        # tokens into reader-visible prose. The strict validator remains the
        # final fail-closed boundary before any renderer can publish content.
        from .survey import PublicSurveyCitationValidator

        drafts, private_content_warnings = self._exclude_private_content(
            drafts, context
        )
        PublicSurveyCitationValidator().validate_stage_drafts(drafts)
        allowed = set(context.allowed_statement_keys)
        statement_citations: dict[str, set[int]] = {}
        for row in evidence_data.evidence_ledger:
            statement_citations.setdefault(row.statement_key, set()).add(row.citation_number)
        all_claims: list[SurveyClaim] = []
        future_directions: list[SurveyFutureDirection] = []
        sections: list[SurveySection] = []
        seen_public_paragraphs: set[str] = set()
        assembly_warnings: list[str] = list(private_content_warnings)
        draft_by_stage = {item.stage: item for item in drafts}
        chinese = context.query_language == "zh"
        section_layout = self._SECTION_LAYOUT_ZH if chinese else self._SECTION_LAYOUT
        for stage, layout in section_layout.items():
            draft = draft_by_stage.get(stage)
            if draft is None:
                continue
            for index, (number, title, section_type) in enumerate(layout):
                section_claims: list[SurveyClaim] = []
                claim_keys: list[str] = []
                for claim in draft.claims if index == 0 else []:
                    keys = list(dict.fromkeys(claim.source_statement_keys))
                    if claim.claim_type is not SurveyClaimType.BACKGROUND and not keys:
                        assembly_warnings.append("UNSUPPORTED_SURVEY_CLAIM_DROPPED")
                        continue
                    if any(key not in allowed for key in keys):
                        raise ReportSchemaValidationError("UNKNOWN_REPORT_STATEMENT_KEY")
                    try:
                        CrossPaperClaimPolicy.validate(claim, set().union(*(statement_citations.get(key, set()) for key in keys)))
                    except ReportSchemaValidationError as error:
                        if str(error) not in {"INSUFFICIENT_CROSS_PAPER_SUPPORT", "UNSUPPORTED_CONSENSUS_LANGUAGE"}:
                            raise
                        assembly_warnings.append(f"{error}_CLAIM_DROPPED")
                        continue
                    citation_tokens = public_citation_refs(keys, evidence_data.evidence_ledger)
                    if keys and not citation_tokens:
                        raise ReportSchemaValidationError("MISSING_CITATION_TOKEN")
                    clean_text = self._strip_generated_citations(claim.text)
                    if not clean_text:
                        assembly_warnings.append("GENERATED_CITATION_ONLY_CLAIM_DROPPED")
                        continue
                    if clean_text != claim.text:
                        assembly_warnings.append("GENERATED_CITATION_TOKEN_REMOVED")
                    item = SurveyClaim(text=clean_text, claim_type=claim.claim_type, certainty=claim.certainty, source_statement_keys=keys, citation_tokens=citation_tokens)
                    section_claims.append(item)
                    all_claims.append(item)
                    claim_keys.extend(keys)
                explicit_paragraphs = [
                    paragraph
                    for paragraph in draft.paragraphs
                    if paragraph.section_type == section_type
                ]
                if any(paragraph.section_type for paragraph in draft.paragraphs):
                    assigned_paragraphs = explicit_paragraphs
                else:
                    # Backwards-compatible deterministic distribution for a
                    # provider that omitted the optional section discriminator.
                    assigned_paragraphs = draft.paragraphs[index::len(layout)]
                paragraphs = []
                for paragraph in assigned_paragraphs:
                    clean_text = self._strip_generated_citations(paragraph.text)
                    if not clean_text:
                        assembly_warnings.append("GENERATED_CITATION_ONLY_PARAGRAPH_DROPPED")
                        continue
                    if clean_text != paragraph.text:
                        assembly_warnings.append("GENERATED_CITATION_TOKEN_REMOVED")
                    normalized_text = clean_text.casefold()
                    if normalized_text in seen_public_paragraphs:
                        continue
                    paragraph_keys = list(dict.fromkeys(paragraph.source_statement_keys))
                    if any(key not in allowed for key in paragraph_keys):
                        raise ReportSchemaValidationError("UNKNOWN_REPORT_STATEMENT_KEY")
                    effective_keys = paragraph_keys or claim_keys
                    refs = public_citation_refs(effective_keys, evidence_data.evidence_ledger)
                    paragraphs.append(SurveyParagraph(text=clean_text, claim_keys=effective_keys, citation_refs=refs))
                    seen_public_paragraphs.add(normalized_text)
                if not paragraphs:
                    paragraphs.append(
                        SurveyParagraph(
                            text=self._insufficient_section_text(
                                section_type, chinese=chinese
                            )
                        )
                    )
                figure_slots = []
                tables = []
                if number == "2":
                    figure_slots.append(SurveyFigureSlot(figure_id="figure-1", figure_type="LITERATURE_TIMELINE_FISHBONE", caption="核心文献时间线与证据覆盖" if chinese else "Core literature timeline and evidence coverage", data_source="LiteratureTimelineEntry[]", timeline_entry_count=len(evidence_data.literature_timeline)))
                if number == "6":
                    tables.append(SurveyTable(table_id="table-1", table_type="COMPARISON_MATRIX", caption="证据驱动的对比矩阵" if chinese else "Evidence-grounded comparison matrix", data_source="ComparisonMatrixData", row_count=len(analysis_data.comparison_matrix.rows)))
                sections.append(SurveySection(section_id=f"section-{number}", number=number, title=title, section_type=section_type, paragraphs=paragraphs, claims=section_claims, tables=tables, figure_slots=figure_slots, warnings=list(draft.warnings)))
            if stage is SynthesisStage.D:
                for direction in draft.future_directions:
                    keys = list(dict.fromkeys(direction.source_statement_keys))
                    if not keys:
                        assembly_warnings.append("UNSUPPORTED_FUTURE_DIRECTION_DROPPED")
                        continue
                    if any(key not in allowed for key in keys):
                        raise ReportSchemaValidationError("UNKNOWN_REPORT_STATEMENT_KEY")
                    citation_tokens = public_citation_refs(keys, evidence_data.evidence_ledger)
                    if direction.kind is FutureDirectionKind.SYNTHESIZED_INFERENCE:
                        cited = set().union(*(statement_citations.get(key, set()) for key in keys))
                        if len(cited) < 2:
                            assembly_warnings.append("INSUFFICIENT_FUTURE_INFERENCE_SUPPORT_DIRECTION_DROPPED")
                            continue
                    clean_text = self._strip_generated_citations(direction.text)
                    if not clean_text:
                        assembly_warnings.append("GENERATED_CITATION_ONLY_DIRECTION_DROPPED")
                        continue
                    if clean_text != direction.text:
                        assembly_warnings.append("GENERATED_CITATION_TOKEN_REMOVED")
                    future_directions.append(SurveyFutureDirection(text=clean_text, kind=direction.kind, source_statement_keys=keys, citation_tokens=citation_tokens))
        report_mode = context.report_mode
        if report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW:
            sections = [item for item in sections if item.number in {"1", "2", "3", "4", "6", "8", "9", "10"}]
        sections = self._apply_deterministic_scope(
            sections, context, evidence_data, facts, chinese=chinese
        )
        title = self._academic_title(context, evidence_data, facts, chinese=chinese)
        abstract = self._structured_abstract(
            context,
            evidence_data,
            analysis_data,
            facts,
            report_mode=report_mode,
            chinese=chinese,
        )
        scope_warning = self._coverage_warning(context, evidence_data, facts, chinese=chinese)
        if scope_warning:
            assembly_warnings.append(scope_warning)
        text_by_type = {item.section_type: " ".join(paragraph.text for paragraph in item.paragraphs) for item in sections}
        raw_warnings = (
            list(context.warnings)
            + list(analysis_data.warnings)
            + [warning for draft in drafts for warning in draft.warnings]
            + assembly_warnings
            + (["EVIDENCE_LIMITED_REVIEW"] if report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW else [])
        )
        preview_markers = ("demo_preview_data", "offline demo uses synthetic papers")
        export_profile = (
            "preview"
            if any(any(marker in warning.casefold() for marker in preview_markers) for warning in raw_warnings)
            else "production"
        )
        warnings = self._public_warnings(
            raw_warnings,
            chinese=chinese,
        )
        metadata = {
            "report_mode": report_mode.value,
            "selected_core_papers": len(evidence_data.core_paper_profiles),
            "verified_evidence": len(evidence_data.evidence_ledger),
            "export_profile": export_profile,
            "citation_style": "GB/T 7714" if chinese else "IEEE",
        }
        if facts:
            metadata.update({key: value for key, value in facts.model_dump().items() if isinstance(value, (int, float))})
            source_labels = [self._source_label(value, chinese=chinese) for value in facts.configured_sources]
            metadata["configured_sources"] = ("\u3001" if chinese else ", ").join(dict.fromkeys(source_labels))
            metadata["source_result_counts"] = ", ".join(
                f"{key}:{value}" for key, value in sorted(facts.source_result_counts.items())
            )
        actual_start, actual_end = self._year_bounds(evidence_data)
        metadata["actual_start_year"] = actual_start
        metadata["actual_end_year"] = actual_end
        return SurveyReport(metadata=metadata, query_language=context.query_language, title=title, abstract=abstract, keywords=self._keywords(context, analysis_data), introduction=text_by_type.get("introduction", ""), literature_method=text_by_type.get("literature_method", ""), evidence_summary=text_by_type.get("comparison", ""), limitations=text_by_type.get("challenges", ""), conclusion=text_by_type.get("conclusion", ""), claims=all_claims, references=list(evidence_data.references), evidence_appendix=list(evidence_data.evidence_ledger), literature_timeline=list(evidence_data.literature_timeline), report_mode=report_mode, warnings=list(dict.fromkeys(warnings)), sections=sections, figures=[figure for section in sections for figure in section.figure_slots], tables=[table for section in sections for table in section.tables], core_paper_profiles=[item.public_dict() for item in evidence_data.core_paper_profiles], taxonomy_summary={"families": [item.public_dict() for item in analysis_data.taxonomy.taxonomy]}, comparison_matrix=analysis_data.comparison_matrix.public_dict(), comparison_facts=analysis_data.comparison_facts.model_dump(mode="json"), future_directions=future_directions)

    @staticmethod
    def _year_bounds(evidence_data: SurveyEvidenceData) -> tuple[int | None, int | None]:
        years = sorted(item.year for item in evidence_data.references if item.year is not None)
        return (years[0], years[-1]) if years else (None, None)

    @staticmethod
    def _requested_bounds(context: SurveyReportContext, facts: LiteratureMethodFacts | None) -> tuple[int | None, int | None]:
        if facts and (facts.requested_start_year or facts.requested_end_year):
            return facts.requested_start_year, facts.requested_end_year
        years = [int(value) for value in re.findall(r"(?:19|20)\d{2}", context.research_question)]
        return (years[0], years[-1]) if len(years) >= 2 else (None, None)

    @staticmethod
    def _source_label(value: str, *, chinese: bool) -> str:
        labels = {
            "arxiv": "arXiv", "semantic_scholar": "Semantic Scholar",
            "google_scholar": "Google Scholar", "cnki": "中国知网（CNKI）" if chinese else "CNKI",
            "openalex": "OpenAlex", "pubmed_central": "PubMed Central",
            "manual": "人工上传" if chinese else "manual upload",
            "user_upload": "人工上传" if chinese else "manual upload",
        }
        return labels.get(value.casefold(), value)

    @classmethod
    def _academic_title(cls, context: SurveyReportContext, evidence_data: SurveyEvidenceData, facts: LiteratureMethodFacts | None, *, chinese: bool) -> str:
        question = " ".join(context.research_question.split()).strip("。；;：: ")
        requested_start, requested_end = cls._requested_bounds(context, facts)
        actual_start, actual_end = cls._year_bounds(evidence_data)
        requested_start = actual_start or requested_start
        requested_end = actual_end or requested_end
        span = f"{requested_start}—{requested_end}年 " if requested_start and requested_end else ""
        if chinese:
            if re.search(r"SLAM|同步定位与建图", question, re.IGNORECASE):
                return f"{span}SLAM 研究综述：技术演进、方法谱系与证据评估"
            cleaned = re.sub(r"^(?:请你?|给出|生成|撰写|整理|调研|分析)\s*", "", question)
            cleaned = re.sub(r"(?:的)?相关(?:文献)?综述$", "", cleaned).strip("的：:，, ")
            return f"{cleaned or '专题研究'}：证据驱动文献综述"
        return f"{question}: Evidence-grounded Literature Survey"

    @classmethod
    def _method_paragraphs(cls, context: SurveyReportContext, evidence_data: SurveyEvidenceData, facts: LiteratureMethodFacts | None, *, chinese: bool) -> list[SurveyParagraph]:
        facts = facts or LiteratureMethodFacts()
        requested_start, requested_end = cls._requested_bounds(context, facts)
        actual_start, actual_end = cls._year_bounds(evidence_data)
        configured = [cls._source_label(value, chinese=chinese) for value in facts.configured_sources if value not in {"google_scholar", "cnki", "user_upload"}]
        sources = ("、".join(dict.fromkeys(configured)) if chinese else ", ".join(dict.fromkeys(configured))) or ("未记录" if chinese else "not recorded")
        requested_span = f"{requested_start}—{requested_end}" if requested_start and requested_end else ("未限定" if chinese else "not constrained")
        actual_span = f"{actual_start}—{actual_end}" if actual_start and actual_end else ("无可核验年份" if chinese else "no verifiable years")
        if chinese:
            source_text = (f"检索范围与来源：配置的发表年份范围为 {requested_span} 年；自动检索渠道为 {sources}。系统计划 {facts.planned_queries} 条检索式，实际执行 {facts.executed_queries} 条，获得 {facts.raw_candidates} 条原始记录，去重后保留 {facts.deduplicated_candidates} 条候选记录。")
            manual_text = ("人工补充机制支持 Google Scholar 与中国知网（CNKI）记录，并要求上传可读取的全文 PDF 后再进入统一证据分析；" f"本次任务纳入 {facts.manual_source_count} 篇人工补充全文。")
            selection_text = (f"筛选与证据化：系统成功读取 {facts.papers_read} 篇全文，经相关性复核后最终纳入 {len(evidence_data.references)} 篇核心文献，并形成 {len(evidence_data.evidence_ledger)} 条可定位证据。报告内核心文献的实际发表年份为 {actual_span} 年。贡献、局限、数据集、指标与结果仅在能够绑定原文页码或章节引文时标记为已验证；缺失项明确保留为空，不以常识补写。")
        else:
            source_text = (f"Scope and sources: the configured publication span was {requested_span}; automated retrieval used {sources}. The system planned {facts.planned_queries} queries, executed {facts.executed_queries}, retrieved {facts.raw_candidates} raw records, and retained {facts.deduplicated_candidates} candidates after deduplication.")
            manual_text = ("The manual supplement workflow accepts Google Scholar and CNKI records only after a readable full-text PDF is uploaded; " f"{facts.manual_source_count} manually supplied papers were included in this run.")
            selection_text = (f"Screening and evidence: {facts.papers_read} full texts were read, {len(evidence_data.references)} core papers were retained, and {len(evidence_data.evidence_ledger)} locatable evidence records were created. The included papers span {actual_span}. Contributions, limitations, datasets, metrics, and results are marked verified only when bound to a page- or section-located quotation; absent fields remain explicit rather than inferred.")
        paragraphs = [SurveyParagraph(text=source_text), SurveyParagraph(text=manual_text), SurveyParagraph(text=selection_text)]
        if facts.source_error_names:
            labels = [cls._source_label(value, chinese=chinese) for value in facts.source_error_names]
            paragraphs.append(SurveyParagraph(text=(f"本次未成功返回结果的渠道：{'、'.join(labels)}；该缺口已计入覆盖范围限制。" if chinese else f"Sources that did not return successfully in this run: {', '.join(labels)}; this gap is treated as a coverage limitation.")))
        return paragraphs

    @classmethod
    def _coverage_warning(cls, context: SurveyReportContext, evidence_data: SurveyEvidenceData, facts: LiteratureMethodFacts | None, *, chinese: bool) -> str | None:
        requested_start, requested_end = cls._requested_bounds(context, facts)
        actual_start, actual_end = cls._year_bounds(evidence_data)
        if not (requested_start and requested_end and actual_start and actual_end):
            return None
        if requested_start >= actual_start and requested_end <= actual_end:
            return None
        if chinese:
            return f"请求范围为 {requested_start}—{requested_end} 年，但本次已核验核心文献实际覆盖 {actual_start}—{actual_end} 年；未覆盖时段不能据本次样本作完整演进判断。"
        return f"The requested span was {requested_start}–{requested_end}, while verified core papers cover {actual_start}–{actual_end}; uncovered years are outside the supported trend claims."

    @classmethod
    def _apply_deterministic_scope(cls, sections: Sequence[SurveySection], context: SurveyReportContext, evidence_data: SurveyEvidenceData, facts: LiteratureMethodFacts | None, *, chinese: bool) -> list[SurveySection]:
        scope_warning = cls._coverage_warning(context, evidence_data, facts, chinese=chinese)
        updated: list[SurveySection] = []
        for section in sections:
            if section.section_type == "literature_method":
                updated.append(section.model_copy(update={"paragraphs": cls._method_paragraphs(context, evidence_data, facts, chinese=chinese)}))
            elif section.section_type == "introduction" and scope_warning:
                updated.append(section.model_copy(update={"paragraphs": [*section.paragraphs, SurveyParagraph(text=scope_warning)]}))
            else:
                updated.append(section)
        return updated

    @classmethod
    def _structured_abstract(cls, context: SurveyReportContext, evidence_data: SurveyEvidenceData, analysis_data: SurveyAnalysisData, facts: LiteratureMethodFacts | None, *, report_mode: ReportMode, chinese: bool) -> str:
        requested_start, requested_end = cls._requested_bounds(context, facts)
        actual_start, actual_end = cls._year_bounds(evidence_data)
        configured = [cls._source_label(value, chinese=chinese) for value in (facts.configured_sources if facts else []) if value not in {"google_scholar", "cnki", "user_upload"}]
        sources = ("、".join(dict.fromkeys(configured)) if chinese else ", ".join(dict.fromkeys(configured))) or ("已配置学术来源" if chinese else "configured scholarly sources")
        requested_span = f"{requested_start}—{requested_end}" if requested_start and requested_end else ("未限定" if chinese else "not constrained")
        actual_span = f"{actual_start}—{actual_end}" if actual_start and actual_end else ("无可核验年份" if chinese else "no verifiable years")
        limitation_count = sum(item.primary_limitation is not None for item in evidence_data.core_paper_profiles)
        family_count = len(analysis_data.taxonomy.taxonomy)
        if chinese:
            limitation = (f"请求时段为 {requested_span} 年，而核心样本实际覆盖 {actual_span} 年；仅 {limitation_count}/{len(evidence_data.references)} 篇论文定位到可验证局限性陈述，结论不外推至未覆盖年份或未取得全文的文献。")
            if report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW:
                limitation += "当前证据规模仅支持范围受限的综述。"
            return (f"背景：围绕“{context.research_question}”梳理研究演进、方法谱系与证据边界。方法：通过 {sources} 自动检索，并支持 Google Scholar/中国知网人工补充全文；对候选文献去重、全文读取、相关性复核，并将论断绑定至原文页码或章节引文。结果：最终纳入 {len(evidence_data.references)} 篇核心论文，形成 {len(evidence_data.evidence_ledger)} 条可定位证据与 {family_count} 个证据支持的方法族。局限：{limitation}")
        limitation = (f"The requested span was {requested_span}, whereas the included core sample spans {actual_span}; verified limitation statements were located for {limitation_count}/{len(evidence_data.references)} papers.")
        if report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW:
            limitation += " The evidence base supports only a bounded review."
        return (f"Background: This survey examines {context.research_question}. Methods: Automated retrieval used {sources}, with manual full-text supplementation from Google Scholar or CNKI, followed by deduplication, full-text reading, relevance review, and quote-level evidence binding. Results: {len(evidence_data.references)} core papers yielded {len(evidence_data.evidence_ledger)} locatable evidence records and {family_count} evidence-supported method families. Limitations: {limitation}")
    @classmethod
    def _strip_generated_citations(cls, value: str) -> str:
        """Remove provider-authored tokens; citations are rebuilt from evidence keys."""

        return " ".join(cls._GENERATED_CITATION.sub("", value).split())
    @staticmethod
    def _public_warnings(warnings: Sequence[str], *, chinese: bool) -> list[str]:
        translations = {
            "DEMO_PREVIEW_DATA": (
                "\u672c\u62a5\u544a\u4f7f\u7528\u7248\u5f0f\u6d4b\u8bd5\u6570\u636e\uff0c\u4ec5\u7528\u4e8e\u9884\u89c8\uff0c\u4e0d\u80fd\u4f5c\u4e3a\u771f\u5b9e\u8c03\u7814\u7ed3\u8bba\u5f15\u7528\u3002"
                if chinese
                else "This report uses layout-test data for preview only and must not be cited as real research."
            ),
            "Offline demo uses synthetic papers and must not be cited as real research.": (
                "\u672c\u62a5\u544a\u4f7f\u7528\u7248\u5f0f\u6d4b\u8bd5\u6570\u636e\uff0c\u4ec5\u7528\u4e8e\u9884\u89c8\uff0c\u4e0d\u80fd\u4f5c\u4e3a\u771f\u5b9e\u8c03\u7814\u7ed3\u8bba\u5f15\u7528\u3002"
                if chinese
                else "This report uses layout-test data for preview only and must not be cited as real research."
            ),
            "FISHBONE_DATA_INCOMPLETE": (
                "部分核心论文缺少可验证的贡献或局限性陈述，时间线会明确显示缺失项。"
                if chinese else "Some core papers lack a verified contribution or limitation; the timeline shows these gaps explicitly."
            ),
            "NO_VERIFIED_LIMITATION": (
                "部分论文未在当前可读取全文中定位到作者明确陈述的局限性。"
                if chinese else "Some papers did not contain an author-stated limitation in the readable full text."
            ),
            "TAXONOMY_CONTEXT_TRUNCATED": (
                "技术分类使用了受上下文长度限制的证据子集。"
                if chinese else "The taxonomy used an evidence subset constrained by the context limit."
            ),
            "TAXONOMY_GENERATION_FAILED": (
                "模型未能生成稳定的技术分类，报告使用了确定性回退分类。"
                if chinese else "The model could not generate a stable taxonomy; a deterministic fallback was used."
            ),
            "TAXONOMY_UNCLASSIFIED_CORE": (
                "部分核心论文因证据不足而保留为未分类。"
                if chinese else "Some core papers remain unclassified because evidence was insufficient."
            ),
            "TAXONOMY_UNAVAILABLE": (
                "现有证据不足以支持稳定的技术分类体系，因此本报告不对方法进行强制分类。"
                if chinese
                else "Available evidence is insufficient for a stable method taxonomy, so methods are not forcibly classified."
            ),
            "EVIDENCE_LIMITED_REVIEW": (
                "当前已验证的文献证据有限，报告结论仅适用于已核验范围。"
                if chinese
                else "Verified literature coverage is limited; conclusions apply only to the assessed evidence."
            ),
            "GENERATED_CITATION_TOKEN_REMOVED": (
                "模型生成文本中的手写引用号已移除，并由系统依据证据键重新生成。"
                if chinese
                else "Provider-authored citation tokens were removed and rebuilt from evidence keys."
            ),
            "GENERATED_CITATION_ONLY_CLAIM_DROPPED": (
                "仅包含手写引用号且没有正文的论断已被排除。"
                if chinese
                else "A claim containing only provider-authored citation tokens was excluded."
            ),
            "GENERATED_CITATION_ONLY_PARAGRAPH_DROPPED": (
                "仅包含手写引用号且没有正文的段落已被排除。"
                if chinese
                else "A paragraph containing only provider-authored citation tokens was excluded."
            ),
            "GENERATED_CITATION_ONLY_DIRECTION_DROPPED": (
                "仅包含手写引用号且没有正文的研究方向已被排除。"
                if chinese
                else "A direction containing only provider-authored citation tokens was excluded."
            ),            "PUBLIC_PRIVATE_LINKAGE_CONTENT_EXCLUDED": (
                "生成文本中不适合公开展示的内部引用片段已被排除。"
                if chinese
                else "A generated fragment containing private linkage metadata was excluded."
            ),
        }
        public: list[str] = []
        for warning in warnings:
            translated = translations.get(warning)
            if translated:
                public.append(translated)
            elif not SurveyPublicContentValidator.contains_internal_identifier(
                warning
            ):
                public.append(warning)
        return list(dict.fromkeys(public))

    @staticmethod
    def _insufficient_section_text(section_type: str, *, chinese: bool) -> str:
        if chinese:
            messages = {
                "introduction": "本报告仅在当前已验证的文献证据范围内概述研究问题与主要发现。",
                "literature_method": "本节说明当前纳入的已验证文献范围；证据不足时不作超出覆盖范围的推断。",
                "background": "当前证据仅支持对研究背景作有限概述，尚不足以形成全面的技术演进判断。",
                "taxonomy": "现有证据不足以支持稳定的技术分类体系，因此本节不对方法进行强制分类。",
                "comparison": "当前已验证的文献证据不足以支持对具体方法性能作确定性比较。",
                "progress": "当前核心文献覆盖不足以形成可靠的方法族研究进展判断。",
                "discussion": "当前证据覆盖不足以支持跨论文的强结论，本节仅陈述可核验的共性与差异。",
                "future": "现有证据不足以提出文献支持的具体未来研究方向。",
                "challenges": "当前未获得足够的已验证局限性证据，因此本节仅说明证据覆盖边界。",
                "conclusion": "在当前证据范围内尚不能形成全面结论，后续判断需要更多直接且可核验的论文证据。",
            }
            return messages.get(
                section_type,
                "当前已验证的文献证据不足以支持本节作出确定性结论。",
            )
        messages = {
            "introduction": "This report outlines the question and findings only within the currently verified literature evidence.",
            "literature_method": "This section states the verified literature scope and does not infer beyond the available evidence.",
            "background": "The available evidence supports only a bounded background overview, not a broad account of technical evolution.",
            "taxonomy": "Available evidence is insufficient for a stable taxonomy, so this section does not force method classifications.",
            "comparison": "Verified literature evidence is insufficient for a definitive comparison of method performance.",
            "progress": "Core-paper coverage is insufficient for a reliable method-family progress assessment.",
            "discussion": "Evidence coverage is insufficient for strong cross-paper conclusions, so this section states only verifiable commonalities and differences.",
            "future": "Available evidence is insufficient for a literature-supported future research direction.",
            "challenges": "Verified limitation evidence is insufficient, so this section states only the evidence boundary.",
            "conclusion": "The current evidence is insufficient for a broad conclusion; further assessment requires more direct, verifiable paper evidence.",
        }
        return messages.get(
            section_type,
            "Verified literature evidence is insufficient for a definitive conclusion in this section.",
        )

    @staticmethod
    def _exclude_private_content(
        drafts: Sequence[SurveyStageDraft], context: SurveyReportContext
    ) -> tuple[list[SurveyStageDraft], list[str]]:
        """Drop only unsafe prose fragments while preserving structured links.

        Provider output occasionally repeats a UUID or an internal field name
        in narrative text even though linkage keys were supplied separately.
        Such prose is never repaired or published: the containing fragment is
        excluded and the report records a deterministic warning.
        """

        from .survey import SurveyPublicContentValidator

        contains_private = SurveyPublicContentValidator.contains_internal_identifier
        cleaned: list[SurveyStageDraft] = []
        removed = False
        chinese = context.query_language == "zh"
        safe_title = "证据驱动研究综述" if chinese else "Evidence-grounded research survey"
        for draft in drafts:
            title = draft.title
            if contains_private(title):
                title = safe_title
                removed = True
            paragraphs = [item for item in draft.paragraphs if not contains_private(item.text)]
            claims = [item for item in draft.claims if not contains_private(item.text)]
            directions = [item for item in draft.future_directions if not contains_private(item.text)]
            warnings = [item for item in draft.warnings if not contains_private(item)]
            removed = removed or any(
                len(before) != len(after)
                for before, after in (
                    (draft.paragraphs, paragraphs),
                    (draft.claims, claims),
                    (draft.future_directions, directions),
                    (draft.warnings, warnings),
                )
            )
            cleaned.append(
                draft.model_copy(
                    update={
                        "title": title,
                        "paragraphs": paragraphs,
                        "claims": claims,
                        "future_directions": directions,
                        "warnings": warnings,
                    }
                )
            )
        warning = "PUBLIC_PRIVATE_LINKAGE_CONTENT_EXCLUDED"
        return cleaned, [warning] if removed else []

    @staticmethod
    def _keywords(context: SurveyReportContext, analysis_data: SurveyAnalysisData) -> list[str]:
        question = context.research_question
        keywords: list[str] = []
        controlled_terms = [
            (r"SLAM", "SLAM"),
            (r"同步定位与建图", "同步定位与建图"),
            (r"视觉", "视觉感知"),
            (r"激光雷达|LiDAR", "LiDAR"),
            (r"多传感器|融合", "多传感器融合"),
            (r"重定位", "重定位"),
            (r"目标检测", "目标检测"),
            (r"深度学习", "深度学习"),
        ]
        for pattern, label in controlled_terms:
            if re.search(pattern, question, re.IGNORECASE):
                keywords.append(label)
        keywords.extend(item.name for item in analysis_data.taxonomy.taxonomy[:4])
        keywords = [
            item for item in keywords
            if not re.search(r"\bmethod\s+family\s+\d+\b", item, re.I)
            and (_CJK_RE.search(item) or len(item.split()) <= 7)
        ]
        keywords.extend(["系统综述", "证据评估"] if context.query_language == "zh" else ["systematic review", "evidence assessment"])
        return list(dict.fromkeys(keywords))[:8]


class SurveySynthesisVerifier:
    """Deterministically enforce structure, mode, and evidence safety."""

    def verify(self, report: SurveyReport, context: SurveyReportContext, analysis_data: SurveyAnalysisData) -> SurveyReport:
        numbers = [section.number for section in report.sections]
        if numbers != sorted(numbers, key=lambda value: [int(part) for part in value.split(".")]):
            raise ReportSchemaValidationError("SECTION_ORDER_ERROR")
        allowed = set(context.allowed_statement_keys)
        for section in report.sections:
            for claim in section.claims:
                if claim.claim_type is not SurveyClaimType.BACKGROUND and not claim.source_statement_keys:
                    raise ReportSchemaValidationError("UNSUPPORTED_SURVEY_CLAIM")
                if any(key not in allowed for key in claim.source_statement_keys):
                    raise ReportSchemaValidationError("UNKNOWN_REPORT_STATEMENT_KEY")
        if report.report_mode is ReportMode.EVIDENCE_LIMITED_REVIEW:
            forbidden = ("comprehensive", "majority of studies", "consensus", "rapidly growing")
            if any(word in report.abstract.casefold() for word in forbidden):
                raise ReportSchemaValidationError("LIMITED_MODE_OVERCLAIM")
        from .survey import PublicSurveyCitationValidator

        PublicSurveyCitationValidator().validate(report)
        return report.model_copy(deep=True)


class FullSurveySynthesisService:
    """Facade for context -> bounded writer stages -> deterministic report."""

    def __init__(self, writer: SurveySynthesisWriter, assembler: SurveySynthesisAssembler | None = None, verifier: SurveySynthesisVerifier | None = None) -> None:
        self.writer = writer
        self.assembler = assembler or SurveySynthesisAssembler()
        self.verifier = verifier or SurveySynthesisVerifier()

    def generate(self, context: SurveyReportContext, evidence_data: SurveyEvidenceData, analysis_data: SurveyAnalysisData, facts: LiteratureMethodFacts | None = None, *, telemetry=None) -> SurveyReport:
        drafts = self.writer.write(context, analysis_data, telemetry=telemetry)
        assembly_started = telemetry.substage_started("assembly") if telemetry is not None else None
        try:
            report = self.assembler.assemble(drafts, context, evidence_data, analysis_data, facts)
        except Exception as error:
            if telemetry is not None:
                telemetry.substage_failed("assembly", assembly_started, error)
            raise
        if telemetry is not None:
            telemetry.substage_completed("assembly", assembly_started)
        validation_started = telemetry.substage_started("citation_safe_validation") if telemetry is not None else None
        if telemetry is not None:
            telemetry.update_input_counts(**self._validation_counts(report))
        try:
            result = self.verifier.verify(report, context, analysis_data)
        except Exception as error:
            if telemetry is not None:
                telemetry.substage_failed("citation_safe_validation", validation_started, error)
            raise
        if telemetry is not None:
            telemetry.substage_completed("citation_safe_validation", validation_started)
        return result

    @staticmethod
    def _validation_counts(report: SurveyReport) -> dict[str, int]:
        """Return scalar-only citation-contract facts for private telemetry."""

        registered = {item.citation_number for item in report.references}
        tokens = [
            token
            for claim in report.claims
            for token in claim.citation_tokens
        ] + [
            token
            for section in report.sections
            for paragraph in section.paragraphs
            for token in paragraph.citation_refs
        ] + [
            token
            for direction in report.future_directions
            for token in direction.citation_tokens
        ]
        cited: set[int] = set()
        for token in tokens:
            for part in re.findall(r"\d+", token):
                cited.add(int(part))
        return {
            "section_count": len(report.sections),
            "body_citation_count": len(tokens),
            "registered_citation_count": len(registered),
            "reference_entry_count": len(report.references),
            "unregistered_citation_count": len(cited - registered),
            "missing_reference_count": len(cited - registered),
            "orphan_reference_count": len(registered - cited),
            "missing_required_field_count": 0,
        }


# Names kept explicit for application/bootstrap integrations.
SurveyReportSynthesisWriter = SurveySynthesisWriter