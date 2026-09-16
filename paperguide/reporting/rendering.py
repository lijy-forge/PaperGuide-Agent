"""Deterministic semantic Markdown and screen HTML renderers for SurveyReport."""

from __future__ import annotations

import html
import re
from enum import Enum

from pydantic import BaseModel, ConfigDict

from .survey import (
    FutureDirectionKind,
    SurveyFigureSlot,
    SurveyReport,
    SurveySection,
    PublicSurveyCitationValidator,
)


class SurveyRenderFormat(str, Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"


class SurveyRenderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str | bytes
    mime_type: str
    extension: str
    warnings: list[str]


class SurveyPresentationStrings:
    """Small localization surface; deliberately not a full i18n framework."""

    _TEXT = {
        "en": {
            "abstract": "Abstract", "keywords": "Keywords", "references": "References",
            "appendix_a": "Appendix A — Core Paper Profiles", "appendix_b": "Appendix B — Evidence Ledger",
            "comparison": "Comparison Matrix", "timeline": "Literature timeline and evidence coverage",
            "scope": "Evidence-limited review: conclusions are bounded by the currently verified literature.",
            "no_limitation": "No verified limitation evidence", "insufficient": "Insufficient information for direct comparison",
            "year_unknown": "Year unavailable", "conflicted": "Conflicting evidence",
            "warnings": "Warnings", "future": "Future Directions", "contents": "Contents",
            "data_source": "Data source", "rows": "rows", "figure_slot": "Figure slot",
            "figure_note": "The semantic timeline data will be rendered graphically in a later renderer stage.",
            "timeline_note": "Timeline fallback data is available in the appendix.",
            "comparison_data": "Comparison data", "citation": "Citation", "paper": "Paper",
            "contribution": "Contribution", "limitation": "Limitation", "year": "Year",
            "statement": "Statement", "status": "Status", "confidence": "Confidence",
            "location": "Location", "quote": "Quote", "method_family": "Method family",
            "evidence_coverage": "Evidence coverage", "unclassified": "Unclassified",
            "verified": "Verified", "partially_supported": "Partially supported",
        },
        "zh": {
            "abstract": "摘要", "keywords": "关键词", "references": "参考文献",
            "appendix_a": "附录 A——核心论文概览", "appendix_b": "附录 B——证据台账",
            "comparison": "对比矩阵", "timeline": "文献时间线与证据覆盖",
            "scope": "证据有限综述：结论仅基于当前已验证的文献范围。",
            "no_limitation": "暂无已验证的局限性证据", "insufficient": "当前信息不足以进行直接比较",
            "year_unknown": "年份未知", "conflicted": "存在冲突证据",
            "warnings": "注意事项", "future": "未来研究方向", "contents": "目录",
            "data_source": "数据来源", "rows": "行", "figure_slot": "图表位置",
            "figure_note": "语义时间线数据将在图形渲染阶段呈现。",
            "timeline_note": "附录中提供时间线的表格化数据。",
            "comparison_data": "对比数据", "citation": "引用", "paper": "论文",
            "contribution": "主要贡献", "limitation": "主要局限", "year": "年份",
            "statement": "陈述", "status": "状态", "confidence": "置信度",
            "location": "定位", "quote": "证据原文", "method_family": "方法族",
            "evidence_coverage": "证据覆盖", "unclassified": "未分类",
            "verified": "已验证", "partially_supported": "部分支持",
        },
    }

    @classmethod
    def get(cls, language: str, key: str) -> str:
        return cls._TEXT.get(language, cls._TEXT["en"]).get(key, cls._TEXT["en"].get(key, key))


def _language(report: SurveyReport) -> str:
    """Use the planned intent locale rather than guessing from report prose."""

    return report.query_language


def _md(value: object) -> str:
    return str(value).replace("\x00", "").replace("\r\n", "\n").replace("<", "&lt;").replace(">", "&gt;").strip()


def _anchor(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff -]+", "", value).strip().lower().replace(" ", "-")
    return value or "section"


def _human_warning(code: str, language: str) -> str | None:
    mapping = {
        "NO_VERIFIED_LIMITATION": "no_limitation",
        "INSUFFICIENT_INFORMATION": "insufficient",
        "EVIDENCE_LIMITED_REVIEW": "scope",
    }
    key = mapping.get(code)
    return SurveyPresentationStrings.get(language, key) if key else None


def _column_label(column: object, language: str) -> str:
    key = str(column)
    presentation = {
        "citation": "citation", "year": "year", "method_family": "method_family",
        "primary_contribution": "contribution", "primary_limitation": "limitation",
        "evidence_coverage": "evidence_coverage",
    }
    chinese = {
        "research_focus": "研究重点", "key_findings": "关键发现", "dataset": "数据集",
        "metric": "指标", "reported_result": "报告结果",
    }
    if language == "zh" and key in chinese:
        return chinese[key]
    mapped = presentation.get(key)
    if mapped:
        return SurveyPresentationStrings.get(language, mapped)
    return key.replace("_", " ").title()


def _status_label(status: str, language: str) -> str:
    key = {"supported": "verified", "partially_supported": "partially_supported", "conflicted": "conflicted"}.get(status)
    return SurveyPresentationStrings.get(language, key) if key else status


class SurveyMarkdownRenderer:
    """Render a SurveyReport as deterministic academic Markdown."""

    def render(self, report: SurveyReport) -> str:
        PublicSurveyCitationValidator().validate(report)
        language = _language(report)
        strings = lambda key: SurveyPresentationStrings.get(language, key)
        lines = [f"# {_md(report.title)}", "", f"{strings('abstract')}", "", _md(report.abstract), ""]
        if report.keywords:
            lines.extend([f"**{strings('keywords')}**: " + ", ".join(_md(item) for item in report.keywords), ""])
        if report.report_mode.value == "evidence_limited_review":
            lines.extend([f"> {strings('scope')}", ""])
        if report.warnings:
            lines.extend([f"## {strings('warnings')}", ""])
            lines.extend(f"- {_md(warning)}" for warning in dict.fromkeys(report.warnings))
            lines.append("")
        for section in report.sections:
            lines.extend(self._section(section, level=2, language=language))
        if report.future_directions:
            lines.extend(["", f"## 9 {strings('future')}", ""])
            for direction in report.future_directions:
                refs = " ".join(direction.citation_tokens)
                lines.append(f"- {_md(direction.text)} {refs}".rstrip())
        lines.extend(self._comparison(report, strings("comparison"), language))
        lines.extend(self._timeline(report, strings("timeline"), language))
        lines.extend(self._references(report, strings("references")))
        lines.extend(self._appendix_profiles(report, strings("appendix_a")))
        lines.extend(self._appendix_ledger(report, strings("appendix_b"), language))
        return "\n".join(lines).rstrip() + "\n"

    def _section(self, section: SurveySection, level: int, language: str) -> list[str]:
        strings = lambda key: SurveyPresentationStrings.get(language, key)
        lines = ["", f"{'#' * level} {section.number} {_md(section.title)}", ""]
        for paragraph in section.paragraphs:
            refs = " ".join(dict.fromkeys(paragraph.citation_refs))
            lines.extend([_md(paragraph.text) + (f" {refs}" if refs else ""), ""])
        if not section.paragraphs:
            for claim in section.claims:
                refs = " ".join(dict.fromkeys(claim.citation_tokens))
                lines.extend([_md(claim.text) + (f" {refs}" if refs else ""), ""])
        for table in section.tables:
            lines.extend([f"### {_md(table.caption)}", "", f"_{strings('data_source')}: {table.data_source}; {strings('rows')}: {table.row_count}._", ""])
        for figure in section.figure_slots:
            lines.extend([f"> {strings('figure_slot')}: {_md(figure.caption)}", f"> {strings('figure_note')}", ""])
        return lines

    def _comparison(self, report: SurveyReport, title: str, language: str) -> list[str]:
        matrix = report.comparison_matrix or {}
        columns = matrix.get("columns", [])
        rows = matrix.get("rows", [])
        if not columns or not rows:
            return []
        lines = ["", f"### {title}", "", "| " + " | ".join(_column_label(column, language) for column in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
        for row in rows:
            cells = row.get("cells", {})
            values = []
            for column in columns:
                cell = cells.get(column, {})
                value = cell.get("value")
                if column == "method_family":
                    value = self._family_name(report, value)
                if value is None:
                    value = "—"
                elif isinstance(value, list):
                    value = "; ".join(map(str, value))
                note = cell.get("notes")
                suffix = f" ({SurveyPresentationStrings.get(language, 'no_limitation')})" if note == "NO_VERIFIED_LIMITATION" else ""
                values.append(_md(value) + suffix)
            lines.append("| " + " | ".join(values) + " |")
        return lines + [""]

    @staticmethod
    def _family_name(report: SurveyReport, value: object) -> object:
        for family in report.taxonomy_summary.get("families", []):
            if family.get("family_key") == value:
                return family.get("name") or "Unclassified"
        return "Unclassified" if value in (None, "UNCLASSIFIED") else value

    def _timeline(self, report: SurveyReport, title: str, language: str) -> list[str]:
        if not report.figures and not report.literature_timeline:
            return []
        strings = lambda key: SurveyPresentationStrings.get(language, key)
        lines = ["", f"> {title}", "", f"| {strings('year')} | {strings('citation')} | {strings('paper')} | {strings('contribution')} | {strings('limitation')} |", "| --- | --- | --- | --- | --- |"]
        for item in report.literature_timeline:
            data = item.public_dict()
            limitation = data.get("primary_limitation") or strings("no_limitation")
            lines.append(f"| {data.get('year') or strings('year_unknown')} | [{data.get('citation_number')}] | {_md(data.get('short_title', ''))} | {_md(data.get('primary_contribution') or '—')} | {_md(limitation)} |")
        return lines + [""]

    def _references(self, report: SurveyReport, title: str) -> list[str]:
        lines = ["", f"## {title}", ""]
        for item in sorted(report.references, key=lambda ref: ref.citation_number):
            authors = ", ".join(item.authors)
            metadata = ", ".join(str(value) for value in (item.venue, item.year) if value)
            source_url = item.source_url or (f"https://arxiv.org/abs/{item.arxiv_id}" if item.arxiv_id else None) or (f"https://doi.org/{item.doi}" if item.doi else None)
            source_label = f"arXiv:{item.arxiv_id}" if item.arxiv_id else f"DOI:{item.doi}" if item.doi else "Source"
            lines.append(f"[{item.citation_number}] {authors}. {_md(item.title)}" + (f". {metadata}" if metadata else "") + "." + (f" [{source_label}]({source_url})" if source_url else ""))
        return lines + [""]

    def _appendix_profiles(self, report: SurveyReport, title: str) -> list[str]:
        language = _language(report)
        strings = lambda key: SurveyPresentationStrings.get(language, key)
        # A profile carries no family field of its own; the taxonomy records
        # membership by citation number, so resolve the name from there.
        families = {
            number: family.get("name")
            for family in report.taxonomy_summary.get("families", [])
            if family.get("name")
            for number in family.get("member_citation_numbers") or []
        }
        lines = ["", f"## {title}", ""]
        for item in report.core_paper_profiles:
            family = families.get(item.get("citation_number")) or strings("unclassified")
            lines.extend([f"### [{item.get('citation_number')}] {_md(item.get('title', ''))}", f"- {strings('year')}: {item.get('year') or strings('year_unknown')}", f"- {strings('method_family')}: {_md(family)}", f"- {strings('evidence_coverage')}: {item.get('verified_evidence_count', 0)}", ""])
        return lines

    def _appendix_ledger(self, report: SurveyReport, title: str, language: str) -> list[str]:
        strings = lambda key: SurveyPresentationStrings.get(language, key)
        lines = ["", f"## {title}", "", f"| {strings('citation')} | {strings('statement')} | {strings('status')} | {strings('confidence')} | {strings('location')} | {strings('quote')} |", "| --- | --- | --- | --- | --- | --- |"]
        for item in report.evidence_appendix:
            status = item.support_status.value
            location = f"p.{item.page}" if item.page else SurveyPresentationStrings.get(language, "year_unknown")
            lines.append(f"| [{item.citation_number}] | {_md(item.statement_text)} | {_status_label(status, language)} | {item.confidence:.2f} | {location} | {_md(item.quote)} |")
        return lines + [""]


class SurveyHtmlRenderer:
    """Render a self-contained, escaped academic screen HTML document."""

    def render(self, report: SurveyReport) -> str:
        PublicSurveyCitationValidator().validate(report)
        language = _language(report)
        md = SurveyMarkdownRenderer()
        toc = "".join(f'<li><a href="#{_anchor(section.section_id)}">{html.escape(section.number)} {html.escape(section.title)}</a></li>' for section in report.sections)
        body = []
        for section in report.sections:
            body.append(self._section(section, language))
        body.append(self._html_comparison(report, language))
        body.append(self._html_timeline(report, language))
        body.append(self._html_references(report, language))
        body.append(self._html_appendices(report, language))
        scope = f'<aside class="scope-note">{html.escape(SurveyPresentationStrings.get(language, "scope"))}</aside>' if report.report_mode.value == "evidence_limited_review" else ""
        warnings = ""
        if report.warnings:
            warnings = f'<aside class="warnings"><strong>{html.escape(SurveyPresentationStrings.get(language, "warnings"))}</strong><ul>' + "".join(
                f"<li>{html.escape(warning)}</li>" for warning in dict.fromkeys(report.warnings)
            ) + "</ul></aside>"
        strings = lambda key: SurveyPresentationStrings.get(language, key)
        return "<!doctype html><html lang=\"" + language + "\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\"><title>" + html.escape(report.title) + "</title><style>" + self._css() + "</style></head><body><article class=\"survey-report\"><header class=\"survey-header\"><h1>" + html.escape(report.title) + "</h1><p class=\"abstract\">" + html.escape(report.abstract) + "</p>" + (f"<p><strong>{html.escape(strings('keywords'))}:</strong> " + html.escape(", ".join(report.keywords)) + "</p>" if report.keywords else "") + scope + warnings + f"</header><nav class=\"toc\"><h2>{html.escape(strings('contents'))}</h2><ol>" + toc + "</ol></nav>" + "".join(body) + "</article></body></html>"

    def _section(self, section: SurveySection, language: str) -> str:
        strings = lambda key: SurveyPresentationStrings.get(language, key)
        content = "".join(f"<p>{html.escape(paragraph.text)} {self._citation_spans(paragraph.citation_refs)}</p>" for paragraph in section.paragraphs)
        if not content:
            content = "".join(f"<p>{html.escape(claim.text)} {self._citation_spans(claim.citation_tokens)}</p>" for claim in section.claims)
        figure = "".join(f'<figure class="figure-placeholder"><figcaption>{html.escape(item.caption)}</figcaption><p>{html.escape(strings("timeline_note"))}</p></figure>' for item in section.figure_slots)
        table = "".join(f'<div class="table-scroll"><p class="table-caption">{html.escape(item.caption)}</p><p>{html.escape(strings("comparison_data"))}: {html.escape(item.data_source)} ({item.row_count} {html.escape(strings("rows"))}).</p></div>' for item in section.tables)
        return f'<section id="{_anchor(section.section_id)}"><h2>{html.escape(section.number)} {html.escape(section.title)}</h2>{content}{table}{figure}</section>'

    @staticmethod
    def _citation_spans(refs: list[str]) -> str:
        return " ".join(f'<span class="citation">{html.escape(ref)}</span>' for ref in dict.fromkeys(refs))

    def _html_comparison(self, report: SurveyReport, language: str) -> str:
        matrix = report.comparison_matrix or {}
        columns, rows = matrix.get("columns", []), matrix.get("rows", [])
        if not columns or not rows:
            return ""
        head = "".join(f"<th>{html.escape(_column_label(column, language))}</th>" for column in columns)
        body = []
        for row in rows:
            cells = row.get("cells", {})
            body.append("<tr>" + "".join("<td>" + html.escape(self._cell_value(cells.get(column, {}), self._family_name(report, cells.get(column, {}).get("value")) if column == "method_family" else None, language=language)) + "</td>" for column in columns) + "</tr>")
        title = SurveyPresentationStrings.get(language, "comparison")
        return f'<div id="comparison-matrix"><h3>{html.escape(title)}</h3><div class="table-scroll"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div></div>'

    @staticmethod
    def _family_name(report: SurveyReport, value: object) -> object:
        for family in report.taxonomy_summary.get("families", []):
            if family.get("family_key") == value:
                return family.get("name") or "Unclassified"
        return "Unclassified" if value in (None, "UNCLASSIFIED") else value

    @staticmethod
    def _cell_value(cell: dict, override: object = None, *, language: str = "en") -> str:
        value = cell.get("value") if override is None else override
        if value is None:
            return "—"
        if isinstance(value, list):
            return "; ".join(map(str, value))
        if cell.get("notes") == "NO_VERIFIED_LIMITATION":
            return f"{value} ({SurveyPresentationStrings.get(language, 'no_limitation')})"
        return str(value)

    def _html_timeline(self, report: SurveyReport, language: str) -> str:
        if not report.literature_timeline:
            return ""
        strings = lambda key: SurveyPresentationStrings.get(language, key)
        rows = []
        for item in report.literature_timeline:
            data = item.public_dict()
            rows.append(f"<tr><td>{html.escape(str(data.get('year') or strings('year_unknown')))}</td><td>[{data.get('citation_number')}]</td><td>{html.escape(data.get('short_title', ''))}</td><td>{html.escape(data.get('primary_contribution') or '—')}</td><td>{html.escape(data.get('primary_limitation') or strings('no_limitation'))}</td></tr>")
        headers = "".join(f"<th>{html.escape(strings(key))}</th>" for key in ("year", "citation", "paper", "contribution", "limitation"))
        return f'<section id="literature-timeline"><h2>{html.escape(strings("timeline"))}</h2><figure class="figure-placeholder"><figcaption>{html.escape(strings("timeline"))}</figcaption><div class="table-scroll"><table><thead><tr>{headers}</tr></thead><tbody>' + "".join(rows) + "</tbody></table></div></figure></section>"

    def _html_references(self, report: SurveyReport, language: str) -> str:
        items = []
        for item in sorted(report.references, key=lambda ref: ref.citation_number):
            source_label = f"arXiv:{item.arxiv_id}" if item.arxiv_id else f"DOI:{item.doi}" if item.doi else ""
            source = f' <span class="source-id">{html.escape(source_label)}</span>' if source_label else ""
            items.append(f'<li id="reference-{item.citation_number}">[{item.citation_number}] {html.escape(", ".join(item.authors))}. {html.escape(item.title)}.{source}</li>')
        items = "".join(items)
        return f'<section id="references"><h2>{html.escape(SurveyPresentationStrings.get(language, "references"))}</h2><ol>{items}</ol></section>'
    def _html_appendices(self, report: SurveyReport, language: str) -> str:
        strings = lambda key: SurveyPresentationStrings.get(language, key)
        profiles = "".join(f"<li>[{item.get('citation_number')}] {html.escape(str(item.get('title', '')))} - {html.escape(strings('evidence_coverage'))}: {item.get('verified_evidence_count', 0)}</li>" for item in report.core_paper_profiles)
        ledger = "".join(f"<tr><td>[{item.citation_number}]</td><td>{html.escape(item.statement_text)}</td><td>{html.escape(_status_label(item.support_status.value, language))}</td><td>{html.escape(item.quote)}</td></tr>" for item in report.evidence_appendix)
        headers = "".join(f"<th>{html.escape(strings(key))}</th>" for key in ("citation", "statement", "status", "quote"))
        return f'<section id="appendix-a"><h2>{html.escape(strings("appendix_a"))}</h2><ul>{profiles}</ul></section><section id="appendix-b"><h2>{html.escape(strings("appendix_b"))}</h2><div class="table-scroll"><table><thead><tr>{headers}</tr></thead><tbody>{ledger}</tbody></table></div></section>'

    @staticmethod
    def _css() -> str:
        return "body{margin:0;background:#f5f6f8;color:#17202a;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.7}article{max-width:820px;margin:0 auto;background:#fff;min-height:100vh;padding:48px 64px;box-sizing:border-box}h1{font-family:Georgia,serif;font-size:2.25rem;line-height:1.2;margin:0 0 1rem}h2{font-family:Georgia,serif;font-size:1.45rem;border-bottom:1px solid #dfe5ea;padding-bottom:.3rem;margin-top:2.4rem}h3{font-family:Georgia,serif}.abstract{font-size:1.05rem;color:#36454f}.scope-note,.warnings{border-left:4px solid #6b7280;background:#f3f4f6;padding:12px 16px;margin:20px 0}.warnings{border-color:#b45309;background:#fffbeb}.warnings ul{margin:6px 0 0;padding-left:20px}.toc{border:1px solid #e3e7eb;padding:16px 24px;margin:28px 0}.toc a{color:#155e75;text-decoration:none}.citation{white-space:nowrap;color:#155e75;font-size:.9em}.table-scroll{overflow-x:auto;margin:16px 0}table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{border:1px solid #d9dee3;padding:8px 10px;text-align:left;vertical-align:top}th{background:#f1f5f7}figure.figure-placeholder{border:1px solid #d9dee3;background:#fafbfc;padding:14px 16px;margin:20px 0}figcaption{font-weight:600}code{overflow-wrap:anywhere}@media(max-width:700px){article{padding:28px 20px}h1{font-size:1.8rem}table{min-width:680px}}"


class SurveyRenderService:
    """Select the deterministic renderer without touching report data."""

    def __init__(self, markdown: SurveyMarkdownRenderer | None = None, html_renderer: SurveyHtmlRenderer | None = None) -> None:
        self.markdown = markdown or SurveyMarkdownRenderer()
        self.html = html_renderer or SurveyHtmlRenderer()
        from .pdf import SurveyPdfRenderer
        self.pdf = SurveyPdfRenderer()

    def render(self, report: SurveyReport, render_format: SurveyRenderFormat | str) -> SurveyRenderResult:
        resolved = SurveyRenderFormat(render_format)
        if resolved is SurveyRenderFormat.MARKDOWN:
            return SurveyRenderResult(content=self.markdown.render(report), mime_type="text/markdown; charset=utf-8", extension=".md", warnings=list(report.warnings))
        if resolved is SurveyRenderFormat.HTML:
            return SurveyRenderResult(content=self.html.render(report), mime_type="text/html; charset=utf-8", extension=".html", warnings=list(report.warnings))
        return SurveyRenderResult(content=self.pdf.render(report), mime_type="application/pdf", extension=".pdf", warnings=list(report.warnings))
