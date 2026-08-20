"""PyMuPDF academic PDF renderer for SurveyReport."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Iterable

from .fishbone import TimelineFishboneRenderer
from .fonts import CJKFontResolver
from .survey import PublicSurveyCitationValidator, SurveyReport


@dataclass(frozen=True)
class SurveyPdfLayoutConfig:
    """Centralized A4 layout constants in points."""

    top_margin: float = 58
    bottom_margin: float = 52
    left_margin: float = 58
    right_margin: float = 58
    header_area: float = 24
    footer_area: float = 24
    body_size: float = 9.5
    heading_size: float = 15
    caption_size: float = 8.5


class SurveyPdfRenderer:
    """Render a report to A4 PDF without browser or extra dependencies."""

    _FONT = "helv"
    _CJK_FONT = "paperpilot-cjk"

    def __init__(self, layout: SurveyPdfLayoutConfig | None = None, fishbone: TimelineFishboneRenderer | None = None, font_resolver: CJKFontResolver | None = None) -> None:
        self.layout = layout or SurveyPdfLayoutConfig()
        self.fishbone = fishbone or TimelineFishboneRenderer()
        self.font_resolver = font_resolver or CJKFontResolver()

    def render(self, report: SurveyReport) -> bytes:
        PublicSurveyCitationValidator().validate(report)
        chinese = self._is_chinese(report)
        # Resolve before creating pages so a Chinese report can never silently
        # fall back to an unembedded built-in CID font.
        if chinese:
            self.font_resolver.resolve()
        try:
            import pymupdf
        except ImportError as error:
            raise RuntimeError("Survey PDF rendering requires PyMuPDF") from error
        document = pymupdf.open()
        page_rect = pymupdf.paper_rect("a4")
        state = {"page": None, "page_index": None, "y": self.layout.top_margin + self.layout.header_area, "left_margin": self.layout.left_margin, "renderer": self}

        def new_page() -> None:
            page = document.new_page(width=page_rect.width, height=page_rect.height)
            state["page"] = page
            state["page_index"] = document.page_count - 1
            state["y"] = self.layout.top_margin + self.layout.header_area
            self._header(page, report)

        def ensure(height: float = 14) -> None:
            if state["page"] is None or state["y"] + height > page_rect.height - self.layout.bottom_margin - self.layout.footer_area:
                new_page()

        def write(text: str, *, size: float | None = None, bold: bool = False, color=(0.1, 0.12, 0.15), gap: float = 5) -> None:
            size = size or self.layout.body_size
            available = page_rect.width - self.layout.left_margin - self.layout.right_margin
            lines = self._wrap(text, max_chars=max(35, int(available / max(5, size * 0.52))))
            for line in lines:
                ensure(size * 1.6)
                state["page"] = document[state["page_index"]]
                self._insert_text(state["page"], (self.layout.left_margin, state["y"]), line, fontsize=size, color=color)
                state["y"] += size * 1.45
            state["y"] += gap

        new_page()
        write(report.title, size=21, bold=True, gap=8)
        write("摘要" if chinese else "Abstract", size=12, bold=True, gap=2)
        write(report.abstract, gap=6)
        if report.keywords:
            write(("关键词：" if chinese else "Keywords: ") + ", ".join(report.keywords), gap=8)
        if report.report_mode.value == "evidence_limited_review":
            write("证据有限综述：结论仅基于当前已验证的文献范围。" if chinese else "Evidence-limited review: conclusions are bounded by the currently verified literature.", gap=8)
        for section in report.sections:
            write(f"{section.number} {section.title}", size=self.layout.heading_size, bold=True, gap=4)
            for paragraph in section.paragraphs:
                refs = " ".join(dict.fromkeys(paragraph.citation_refs))
                write(paragraph.text + (f" {refs}" if refs else ""), gap=4)
            for figure in section.figure_slots:
                self._figure_slot(state, ensure, write, report)
            for table in section.tables:
                write(table.caption, size=11, bold=True)
                self._comparison_text(state, ensure, report, chinese=chinese)

        if report.literature_timeline:
            write("文献时间线与证据覆盖" if chinese else "Literature timeline and evidence coverage", size=self.layout.heading_size, bold=True)
            groups = self.fishbone.group_entries(report.literature_timeline)
            for group_index, group_entries in enumerate(groups, start=1):
                self._fishbone_page(document, group_entries, page_rect, group_index, chinese=chinese)
            new_page()
        if report.references:
            write("参考文献" if chinese else "References", size=self.layout.heading_size, bold=True)
            for item in sorted(report.references, key=lambda ref: ref.citation_number):
                metadata = ", ".join(str(value) for value in (item.venue, item.year) if value)
                write(f"[{item.citation_number}] {', '.join(item.authors)}. {item.title}. {metadata}", gap=3)
        if report.core_paper_profiles:
            write("附录 A——核心论文概览" if chinese else "Appendix A - Core Paper Profiles", size=self.layout.heading_size, bold=True)
            for item in report.core_paper_profiles:
                write(f"[{item.get('citation_number')}] {item.get('title', '')}", size=10.5, bold=True, gap=2)
                write((f"年份：{item.get('year') or '未知'}；证据覆盖：{item.get('verified_evidence_count', 0)}" if chinese else f"Year: {item.get('year') or 'Year unavailable'}; Evidence coverage: {item.get('verified_evidence_count', 0)}"), gap=3)
        if report.evidence_appendix:
            write("附录 B——证据台账" if chinese else "Appendix B - Evidence Ledger", size=self.layout.heading_size, bold=True)
            for item in report.evidence_appendix:
                status = self._status(item.support_status.value, chinese=chinese)
                location = f"第 {item.page} 页" if chinese and item.page else (f"p.{item.page}" if item.page else ("位置不可用" if chinese else "Location unavailable"))
                write((f"[{item.citation_number}] {item.statement_text}——{status}，置信度 {item.confidence:.2f}，{location}" if chinese else f"[{item.citation_number}] {item.statement_text} - {status}, confidence {item.confidence:.2f}, {location}"), gap=2)
                write((f"原文引用：{item.quote}" if chinese else f"Quote: {item.quote}"), size=8.5, gap=4)
        for index in range(document.page_count):
            self._footer(document[index], index + 1, document.page_count, chinese=chinese)
        document.set_metadata({"title": report.title, "subject": "Evidence-grounded academic survey", "keywords": ", ".join(report.keywords), "creator": "PaperPilot AI", "producer": "PyMuPDF"})
        payload = document.tobytes(garbage=4, deflate=True)
        document.close()
        return payload

    def export(self, report: SurveyReport, output_path: str | Path) -> str:
        path = Path(output_path)
        path.write_bytes(self.render(report))
        return str(path.resolve())

    def _comparison_text(self, state, ensure, report: SurveyReport, *, chinese: bool) -> None:
        matrix = report.comparison_matrix or {}
        columns, rows = matrix.get("columns", []), matrix.get("rows", [])
        if not columns or not rows:
            message = "缺少可直接比较的已验证信息" if chinese else "Insufficient information for direct comparison"
            self._insert_text(state["page"], (self.layout.left_margin, state["y"]), message, fontsize=self.layout.body_size)
            state["y"] += 18
            return
        for row in rows:
            values = []
            for column in columns:
                cell = row.get("cells", {}).get(column, {})
                value = cell.get("value")
                if column == "method_family" and value is not None:
                    value = self._family_name(report, value)
                if value is None:
                    value = "—"
                elif isinstance(value, list):
                    value = "; ".join(map(str, value))
                if cell.get("notes") == "NO_VERIFIED_LIMITATION":
                    value = "暂无已验证的局限性证据" if chinese else "No verified limitation evidence"
                values.append(f"{self._column_label(column, chinese=chinese)}: {value}")
            self._write_lines(state, ensure, " | ".join(values), size=8.5)

    @staticmethod
    def _column_label(column: object, *, chinese: bool = False) -> str:
        labels_en = {
            "citation": "Citation",
            "year": "Year",
            "method_family": "Method family",
            "research_focus": "Research focus",
            "primary_contribution": "Primary contribution",
            "key_findings": "Key findings",
            "primary_limitation": "Primary limitation",
            "evidence_coverage": "Evidence coverage",
            "dataset": "Dataset",
            "metric": "Metric",
            "reported_result": "Reported result",
            "datasets": "Datasets",
            "metrics": "Metrics",
            "baselines": "Baselines",
        }
        labels_zh = {
            "citation": "引用",
            "year": "年份",
            "method_family": "方法族",
            "research_focus": "研究重点",
            "primary_contribution": "主要贡献",
            "key_findings": "关键发现",
            "primary_limitation": "主要局限",
            "evidence_coverage": "证据覆盖",
            "dataset": "数据集",
            "metric": "指标",
            "reported_result": "报告结果",
            "datasets": "数据集",
            "metrics": "指标",
            "baselines": "基线",
        }
        labels = labels_zh if chinese else labels_en
        return labels.get(str(column), str(column).replace("_", " ").title())

    @staticmethod
    def _family_name(report: SurveyReport, value: object) -> object:
        for family in report.taxonomy_summary.get("families", []):
            if family.get("family_key") == value:
                return family.get("name") or family.get("label") or value
        return value

    def _figure_slot(self, state, ensure, write, report) -> None:
        if self._is_chinese(report):
            write("图 1——核心文献时间线演化", size=10.5, bold=True, gap=2)
            write("下一页展示矢量时间线；其中的贡献与局限均来自已验证并完成证据关联的陈述。", size=8.5, gap=5)
        else:
            write("Figure 1 - Timeline evolution of core literature", size=10.5, bold=True, gap=2)
            write("The vector timeline figure is included on the following page. Contributions and limitations are derived from verified evidence-linked statements.", size=8.5, gap=5)

    def _fishbone_page(self, document, entries, page_rect, figure_number: int, *, chinese: bool) -> None:
        page = document.new_page(width=page_rect.width, height=page_rect.height)
        caption = "图 1——核心文献时间线演化" if chinese else "Figure 1 - Timeline evolution of core literature"
        if figure_number > 1:
            caption += f" ({figure_number})"
        self._insert_text(page, (self.layout.left_margin, self.layout.top_margin), caption, fontsize=12)
        entries = list(entries)
        spine_y = page_rect.height / 2
        left, right = self.layout.left_margin, page_rect.width - self.layout.right_margin
        page.draw_line((left, spine_y), (right, spine_y), color=(0.2, 0.3, 0.4), width=1.2)
        if not entries:
            message = "暂无足够的核心文献时间线数据。" if chinese else "No sufficient core literature timeline data."
            self._insert_text(page, (left, spine_y), message, fontsize=9)
            return
        step = (right - left) / max(1, len(entries) - 1)
        for index, entry in enumerate(entries):
            x = left + index * step
            above = index % 2 == 0
            y = spine_y - 72 if above else spine_y + 72
            page.draw_line((x, spine_y), (x, y), color=(0.4, 0.5, 0.6), width=0.8)
            page.draw_circle((x, spine_y), 3, color=(0.05, 0.45, 0.42), fill=(0.05, 0.45, 0.42))
            year = str(entry.year) if entry.year is not None else ("年份未知" if chinese else "Year unavailable")
            title = self._truncate(entry.short_title, 26)
            contribution = self._truncate(entry.primary_contribution or ("暂无已验证的贡献证据" if chinese else "No verified contribution evidence"), 30)
            limitation = self._truncate(entry.primary_limitation or ("暂无已验证的局限性证据" if chinese else "No verified limitation evidence"), 30)
            lines = [
                f"{year} [{entry.citation_number}] {title}",
                f"{'贡献' if chinese else 'Contribution'}: {contribution}",
                f"{'局限' if chinese else 'Limitation'}: {limitation}",
            ]
            box_top = y - 42 if above else y
            box_left = min(max(left, x - 70), right - 140)
            for offset, line in enumerate(lines):
                self._insert_text(page, (box_left, box_top + offset * 12), line, fontsize=7.2)

    @staticmethod
    def _write_lines(state, ensure, text: str, *, size: float) -> None:
        lines = SurveyPdfRenderer._wrap(text, max_chars=105)
        for line in lines:
            ensure(size * 1.5)
            state["renderer"]._insert_text(state["page"], (state.get("left_margin", 58), state["y"]), line, fontsize=size)
            state["y"] += size * 1.4
        state["y"] += 3

    @staticmethod
    def _wrap(text: str, max_chars: int) -> list[str]:
        normalized = str(text).replace("\r", "").replace("\n", " ").strip()
        # Chinese paragraphs normally contain no spaces. Treat every CJK glyph
        # as two Latin character units while retaining Latin words as tokens.
        words = re.findall(r"[\u3400-\u9fff]|[^\s\u3400-\u9fff]+", normalized)
        lines: list[str] = []
        current = ""
        for word in words:
            separator = "" if re.search(r"[\u3400-\u9fff]$", current) or re.match(r"[\u3400-\u9fff]", word) else " "
            candidate = f"{current}{separator}{word}" if current else word
            if current and SurveyPdfRenderer._display_units(candidate) > max_chars:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines or [""]

    @staticmethod
    def _display_units(text: str) -> int:
        return sum(2 if "\u3400" <= character <= "\u9fff" else 1 for character in text)

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        text = " ".join(str(text).split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    @staticmethod
    def _status(status: str, *, chinese: bool = False) -> str:
        if chinese:
            return {"supported": "已验证", "partially_supported": "部分支持", "conflicted": "证据冲突"}.get(status, "证据状态不可用")
        return {"supported": "Verified", "partially_supported": "Partially supported", "conflicted": "Conflicting evidence"}.get(status, "Evidence status unavailable")

    def _header(self, page, report: SurveyReport) -> None:
        self._insert_text(page, (self.layout.left_margin, 28), self._truncate(report.title, 90), fontsize=8, color=(0.25, 0.3, 0.35))

    def _footer(self, page, number: int, total: int, *, chinese: bool = False) -> None:
        label = "PaperPilot AI——证据驱动技术综述" if chinese else "PaperPilot AI - Evidence-grounded survey"
        self._insert_text(page, (self.layout.left_margin, page.rect.height - 24), label, fontsize=7.5, color=(0.35, 0.4, 0.45))
        self._insert_text(page, (page.rect.width - self.layout.right_margin - 55, page.rect.height - 24), f"{number} / {total}", fontsize=7.5, color=(0.35, 0.4, 0.45))

    def _insert_text(self, page, point, text: str, **kwargs) -> None:
        if not re.search(r"[\u3400-\u9fff]", text):
            page.insert_text(point, text, fontname=self._FONT, **kwargs)
            return
        # One real font handles the whole mixed CJK/Latin run. Supplying
        # ``fontfile`` makes PyMuPDF embed the font program into the PDF, so
        # PDF.js does not depend on fonts installed on the browser host.
        page.insert_text(
            point,
            text,
            fontname=self._CJK_FONT,
            fontfile=str(self.font_resolver.resolve()),
            **kwargs,
        )

    @staticmethod
    def _is_chinese(report: SurveyReport) -> bool:
        """Use the planned intent locale rather than rendered-text heuristics."""

        return report.query_language == "zh"
