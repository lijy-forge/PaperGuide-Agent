"""PyMuPDF academic PDF renderer for SurveyReport."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Iterable

from .fishbone import TimelineFishboneRenderer
from .fonts import CJKFontResolver
from .survey import PublicSurveyCitationValidator, SurveyParagraph, SurveyReport, SurveySection


@dataclass(frozen=True)
class SurveyPdfLayoutConfig:
    """Centralized A4 layout constants in points."""

    top_margin: float = 58
    bottom_margin: float = 52
    left_margin: float = 58
    right_margin: float = 58
    header_area: float = 24
    footer_area: float = 24
    body_size: float = 10
    heading_size: float = 15
    caption_size: float = 8.5


class SurveyPdfRenderer:
    """Render a report to A4 PDF without browser or extra dependencies."""

    _FONT = "helv"
    _CJK_FONT = "paperguide-cjk"

    def __init__(self, layout: SurveyPdfLayoutConfig | None = None, fishbone: TimelineFishboneRenderer | None = None, font_resolver: CJKFontResolver | None = None) -> None:
        self.layout = layout or SurveyPdfLayoutConfig()
        self.fishbone = fishbone or TimelineFishboneRenderer()
        self.font_resolver = font_resolver or CJKFontResolver()

    def render(self, report: SurveyReport) -> bytes:
        PublicSurveyCitationValidator().validate(report)
        chinese = self._is_chinese(report)
        if chinese:
            self.font_resolver.resolve()
        try:
            import pymupdf
        except ImportError as error:
            raise RuntimeError("Survey PDF rendering requires PyMuPDF") from error

        document = pymupdf.open()
        page_rect = pymupdf.paper_rect("a4")
        state = {
            "page": None,
            "page_index": None,
            "y": self.layout.top_margin + self.layout.header_area,
            "left_margin": self.layout.left_margin,
            "renderer": self,
        }
        toc_items: list[tuple[int, str, int]] = []

        def new_page(*, header: bool = True) -> None:
            page = document.new_page(width=page_rect.width, height=page_rect.height)
            state["page"] = page
            state["page_index"] = document.page_count - 1
            state["y"] = self.layout.top_margin + self.layout.header_area
            if header:
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

        # Cover
        new_page(header=False)
        state["page"].draw_rect(
            pymupdf.Rect(0, 0, page_rect.width, 232),
            color=(0.035, 0.105, 0.18),
            fill=(0.035, 0.105, 0.18),
            overlay=True,
        )
        state["page"].draw_rect(
            pymupdf.Rect(0, 228, page_rect.width, 232),
            color=(0.04, 0.48, 0.45),
            fill=(0.04, 0.48, 0.45),
            overlay=True,
        )
        state["y"] = 60
        write("PAPERGUIDE AI  /  EVIDENCE-GROUNDED SURVEY", size=8.5, color=(0.62, 0.86, 0.86), gap=13)
        write(report.title, size=21, bold=True, color=(1, 1, 1), gap=11)
        state["y"] = 252
        self._summary_cards(state, ensure, report, page_rect, chinese=chinese)
        write("结构化摘要" if chinese else "Structured abstract", size=12, bold=True, color=(0.04, 0.28, 0.35), gap=3)
        write(report.abstract, size=9.2, gap=6)
        if report.keywords:
            write(("关键词：" if chinese else "Keywords: ") + " · ".join(report.keywords), size=8.4, color=(0.25, 0.36, 0.40), gap=8)
        write("核心结论" if chinese else "Executive takeaways", size=11.5, bold=True, color=(0.04, 0.28, 0.35), gap=2)
        for takeaway in self._executive_takeaways(report, chinese=chinese):
            write(f"• {takeaway}", size=8.7, gap=2)
        if report.warnings:
            write(("证据边界：" if chinese else "Evidence boundary: ") + report.warnings[0], size=8, color=(0.55, 0.30, 0.08), gap=4)
        self._cover_guide(state, report, chinese=chinese)

        # Reserve a table-of-contents page and populate it once pagination is known.
        new_page()
        toc_page_index = state["page_index"]
        new_page()
        body_top = self.layout.top_margin + self.layout.header_area
        major_starts = {"3", "6", "8"}
        for section in report.sections:
            if section.number in major_starts and state["y"] > body_top + 20:
                new_page()
            ensure(34)
            toc_items.append((1, f"{section.number} {section.title}", state["page_index"] + 1))
            write(f"{section.number} {section.title}", size=self.layout.heading_size, bold=True, color=(0.04, 0.28, 0.35), gap=5)
            for paragraph in section.paragraphs:
                refs = " ".join(dict.fromkeys(paragraph.citation_refs))
                write(paragraph.text + (f" {refs}" if refs else ""), gap=4)
            if section.number == "2":
                self._retrieval_flow(state, ensure, report, chinese=chinese)
            if section.number == "4" and report.taxonomy_summary.get("families"):
                self._taxonomy_overview(state, ensure, report, chinese=chinese)
            if section.number == "7":
                self._method_spotlight(state, ensure, report, chinese=chinese)
            for figure in section.figure_slots:
                self._figure_slot(state, ensure, write, report)
            for table in section.tables:
                write(table.caption, size=11, bold=True, color=(0.04, 0.28, 0.35))
                self._comparison_text(state, ensure, report, chinese=chinese)

        if report.literature_timeline:
            groups = self._timeline_page_groups(report.literature_timeline)
            timeline_page = document.page_count + 1
            toc_items.append((1, "文献时间线与证据覆盖" if chinese else "Literature timeline and evidence coverage", timeline_page))
            for group_index, group_entries in enumerate(groups, start=1):
                self._fishbone_page(document, group_entries, page_rect, group_index, len(groups), chinese=chinese)

        if report.references:
            new_page()
            toc_items.append((1, "参考文献" if chinese else "References", state["page_index"] + 1))
            write("参考文献" if chinese else "References", size=self.layout.heading_size, bold=True, color=(0.04, 0.28, 0.35))
            self._reference_entries(state, ensure, write, report, chinese=chinese)

        if report.core_paper_profiles:
            new_page()
            toc_items.append((1, "附录 A——核心论文概览" if chinese else "Appendix A - Core Paper Profiles", state["page_index"] + 1))
            write("附录 A——核心论文概览" if chinese else "Appendix A - Core Paper Profiles", size=self.layout.heading_size, bold=True, color=(0.04, 0.28, 0.35))
            self._profile_cards(state, ensure, report, chinese=chinese)

        if report.evidence_appendix:
            new_page()
            toc_items.append((1, "附录 B——证据台账" if chinese else "Appendix B - Evidence Ledger", state["page_index"] + 1))
            write("附录 B——证据台账" if chinese else "Appendix B - Evidence Ledger", size=self.layout.heading_size, bold=True, color=(0.04, 0.28, 0.35))
            self._evidence_ledger_cards(state, ensure, report, chinese=chinese)

        self._render_toc(document[toc_page_index], toc_items, report, chinese=chinese)
        outline = [[1, report.title, 1], [1, "目录" if chinese else "Contents", toc_page_index + 1]]
        outline.extend([[level, title, page_number] for level, title, page_number in toc_items])
        document.set_toc(outline)
        for index in range(document.page_count):
            if str(report.metadata.get("export_profile") or "").casefold() == "preview":
                self._preview_watermark(document[index], chinese=chinese)
            self._footer(document[index], index + 1, document.page_count, chinese=chinese)
        document.set_metadata({
            "title": report.title,
            "subject": "Evidence-grounded academic survey",
            "keywords": ", ".join(report.keywords),
            "creator": "PaperGuide AI",
            "producer": "PyMuPDF",
        })
        try:
            document.subset_fonts()
        except Exception:
            pass
        try:
            payload = document.tobytes(
                garbage=4,
                deflate=True,
                deflate_fonts=True,
                deflate_images=True,
                use_objstms=1,
            )
        except TypeError:
            payload = document.tobytes(garbage=4, deflate=True, deflate_fonts=True, deflate_images=True)
        document.close()
        return payload

    def export(self, report: SurveyReport, output_path: str | Path) -> str:
        path = Path(output_path)
        path.write_bytes(self.render(report))
        return str(path.resolve())

    def _cover_guide(self, state, report: SurveyReport, *, chinese: bool) -> None:
        """Use the lower cover area for practical reading guidance."""

        page = state["page"]
        top = max(state["y"] + 8, 535)
        height = 92
        if top + height > page.rect.height - self.layout.bottom_margin - self.layout.footer_area:
            return
        left = self.layout.left_margin
        available = page.rect.width - self.layout.left_margin - self.layout.right_margin
        gap = 9
        width = (available - gap * 2) / 3
        years = [item.year for item in report.references if item.year is not None]
        actual = f"{min(years)}—{max(years)}" if years else "—"
        cards = (
            [
                ("本报告回答", f"方法谱系、跨论文差异与未来挑战；实际样本覆盖 {actual} 年。"),
                ("证据规则", "正文引用可追溯至参考文献；贡献与局限缺失时不作推断补写。"),
                ("建议阅读", "先读目录与对比矩阵，再查看时间线；争议项回到附录 B 原文引文。"),
            ]
            if chinese
            else [
                ("Questions", f"Method families, cross-paper differences, and future challenges; included span {actual}."),
                ("Evidence rule", "Claims trace to references; missing contributions and limitations are not inferred."),
                ("Reading path", "Start with contents and the matrix, then the timeline; audit claims in Appendix B."),
            ]
        )
        for index, (label, body) in enumerate(cards):
            x0 = left + index * (width + gap)
            page.draw_rect((x0, top, x0 + width, top + height), color=(0.80, 0.86, 0.88), fill=(0.97, 0.985, 0.985), width=0.6)
            page.draw_rect((x0, top, x0 + 4, top + height), color=(0.04, 0.48, 0.45), fill=(0.04, 0.48, 0.45), width=0)
            self._insert_text(page, (x0 + 12, top + 20), label, fontsize=8.5, color=(0.04, 0.28, 0.35))
            body_lines = self._limited_lines(body, max_chars=27, max_lines=4)
            self._insert_text_lines(page, x0 + 12, top + 40, body_lines, fontsize=7.4, line_gap=10, color=(0.28, 0.34, 0.37))
        state["y"] = top + height + 8

    def _retrieval_flow(self, state, ensure, report: SurveyReport, *, chinese: bool) -> None:
        """Show the deterministic literature funnel recorded by the task runtime."""

        ensure(82)
        page = state["page"]
        top = state["y"] + 3
        values = [
            report.metadata.get("executed_queries", 0),
            report.metadata.get("raw_candidates", 0),
            report.metadata.get("deduplicated_candidates", 0),
            report.metadata.get("papers_read", 0),
            len(report.references),
        ]
        labels = (["执行检索式", "原始记录", "去重候选", "全文读取", "核心纳入"] if chinese else ["Queries", "Raw records", "Deduplicated", "Full texts", "Core included"])
        left = self.layout.left_margin
        available = page.rect.width - self.layout.left_margin - self.layout.right_margin
        gap = 11
        width = (available - gap * 4) / 5
        height = 50
        self._insert_text(page, (left, top), "检索与筛选流程" if chinese else "Retrieval and screening funnel", fontsize=9.2, color=(0.04, 0.28, 0.35))
        box_top = top + 12
        for index, (label, value) in enumerate(zip(labels, values)):
            x0 = left + index * (width + gap)
            page.draw_rect((x0, box_top, x0 + width, box_top + height), color=(0.73, 0.82, 0.84), fill=(0.95, 0.975, 0.975), width=0.55)
            self._insert_text(page, (x0 + 7, box_top + 17), label, fontsize=6.8, color=(0.34, 0.42, 0.46))
            self._insert_text(page, (x0 + 7, box_top + 38), str(value), fontsize=11, color=(0.04, 0.34, 0.37))
            if index < 4:
                y = box_top + height / 2
                page.draw_line((x0 + width + 2, y), (x0 + width + gap - 2, y), color=(0.25, 0.51, 0.53), width=1)
        state["y"] = box_top + height + 12
    def _executive_takeaways(self, report: SurveyReport, *, chinese: bool) -> list[str]:
        takeaways: list[str] = []
        for claim in report.claims[:3]:
            refs = " ".join(dict.fromkeys(claim.citation_tokens))
            text = self._truncate(claim.text, 120)
            takeaways.append(text + (f" {refs}" if refs else ""))
        years = [item.year for item in report.references if item.year is not None]
        if len(takeaways) < 3 and years:
            takeaways.append(
                (f"本次可核验核心样本实际覆盖 {min(years)}—{max(years)} 年，共 {len(report.references)} 篇；未覆盖年份不作完整演进判断。"
                 if chinese else f"The verified core sample spans {min(years)}–{max(years)} and contains {len(report.references)} papers; uncovered years are not used for complete trend claims.")
            )
        families = report.taxonomy_summary.get("families", [])
        if len(takeaways) < 3:
            takeaways.append(
                (f"基于全文证据归纳出 {len(families)} 个方法族；无法稳定归类的论文保留为未分类。"
                 if chinese else f"Full-text evidence supports {len(families)} method families; papers without stable support remain unclassified.")
            )
        missing_limitations = sum(not item.get("primary_limitation") for item in report.core_paper_profiles)
        if len(takeaways) < 3:
            takeaways.append(
                (f"{missing_limitations} 篇核心论文未定位到作者明确陈述的局限，系统保留缺失标记而不推断补写。"
                 if chinese else f"No author-stated limitation was located for {missing_limitations} core papers; gaps remain explicit rather than inferred.")
            )
        return takeaways[:3]

    def _render_toc(self, page, items, report: SurveyReport, *, chinese: bool) -> None:
        rect_type = type(page.rect)
        self._insert_text(page, (self.layout.left_margin, 86), "目录" if chinese else "Contents", fontsize=20, color=(0.04, 0.20, 0.28))
        source_text = str(report.metadata.get("configured_sources") or "")
        requested_start = report.metadata.get("requested_start_year")
        requested_end = report.metadata.get("requested_end_year")
        actual_start = report.metadata.get("actual_start_year")
        actual_end = report.metadata.get("actual_end_year")
        if chinese:
            scope = f"请求范围 {requested_start or '—'}—{requested_end or '—'} 年  ·  实际核心样本 {actual_start or '—'}—{actual_end or '—'} 年  ·  自动来源 {source_text or '未记录'}"
        else:
            scope = f"Requested {requested_start or '—'}–{requested_end or '—'}  ·  Included {actual_start or '—'}–{actual_end or '—'}  ·  Sources {source_text or 'not recorded'}"
        self._insert_text(page, (self.layout.left_margin, 110), self._truncate(scope, 105), fontsize=8.2, color=(0.35, 0.43, 0.48))
        y = 145
        width = page.rect.width - self.layout.left_margin - self.layout.right_margin
        for _, title, target in items:
            label = self._truncate(title, 62)
            dots = "·" * max(3, 54 - self._display_units(label) // 2)
            line = f"{label}  {dots}  {target}"
            self._insert_text(page, (self.layout.left_margin, y), line, fontsize=9.5, color=(0.08, 0.18, 0.23))
            page.insert_link({"kind": 1, "from": rect_type(self.layout.left_margin, y - 11, self.layout.left_margin + width, y + 4), "page": target - 1})
            y += 25

    def _reference_entries(self, state, ensure, write, report: SurveyReport, *, chinese: bool) -> None:
        for item in sorted(report.references, key=lambda ref: ref.citation_number):
            ensure(58)
            metadata = ", ".join(str(value) for value in (item.venue, item.year) if value)
            authors = ", ".join(item.authors) or ("作者未知" if chinese else "Authors unavailable")
            write(f"[{item.citation_number}] {authors}. {item.title}. {metadata}", size=8.9, gap=2)
            source_text, source_url = self._timeline_source(item, chinese=chinese)
            source_y = state["y"]
            source_page_index = state["page_index"]
            write(source_text + (f" · {source_url}" if source_url else ""), size=7.3, color=(0.08, 0.35, 0.55), gap=5)
            if source_url and source_page_index == state["page_index"]:
                page = state["page"]
                rect_type = type(page.rect)
                page.insert_link({"kind": 2, "from": rect_type(self.layout.left_margin, source_y - 9, page.rect.width - self.layout.right_margin, min(state["y"], source_y + 22)), "uri": source_url})

    def _profile_cards(self, state, ensure, report: SurveyReport, *, chinese: bool) -> None:
        for item in report.core_paper_profiles:
            ensure(94)
            top = state["y"]
            page = state["page"]
            right = page.rect.width - self.layout.right_margin
            page.draw_rect((self.layout.left_margin, top - 8, right, top + 76), color=(0.80, 0.86, 0.88), fill=(0.975, 0.985, 0.985), width=0.6)
            citation = item.get("citation_number")
            title = self._limited_lines(str(item.get("title") or ""), max_chars=92, max_lines=1)
            self._insert_text(page, (self.layout.left_margin + 8, top + 8), f"[{citation}] {title}", fontsize=9.3, color=(0.04, 0.28, 0.35))
            meta = (f"年份 {item.get('year') or '未知'}  ·  已验证证据 {item.get('verified_evidence_count', 0)} 条" if chinese else f"Year {item.get('year') or 'N/A'}  ·  Verified evidence {item.get('verified_evidence_count', 0)}")
            self._insert_text(page, (self.layout.left_margin + 8, top + 24), meta, fontsize=7.2, color=(0.36, 0.43, 0.47))
            contribution = item.get("primary_contribution") or {}
            contribution_text = contribution.get("text") if isinstance(contribution, dict) else str(contribution or "")
            if not contribution_text:
                findings = item.get("key_findings") or []
                first = findings[0] if findings else {}
                contribution_text = first.get("text") if isinstance(first, dict) else str(first or "")
                contribution_label = "关键发现" if chinese else "Key finding"
            else:
                contribution_label = "主要贡献" if chinese else "Contribution"
            limitation = item.get("primary_limitation") or {}
            limitation_text = limitation.get("text") if isinstance(limitation, dict) else str(limitation or "")
            contribution_text = contribution_text or ("未定位到可验证贡献" if chinese else "No verified contribution located")
            limitation_text = limitation_text or ("未定位到作者明确陈述的局限" if chinese else "No author-stated limitation located")
            self._insert_text_lines(page, self.layout.left_margin + 8, top + 42, f"{contribution_label}：{self._limited_lines(contribution_text, max_chars=82, max_lines=1)}", fontsize=7.6, line_gap=9, color=(0.20, 0.28, 0.31))
            self._insert_text_lines(page, self.layout.left_margin + 8, top + 59, f"{'局限' if chinese else 'Limitation'}：{self._limited_lines(limitation_text, max_chars=82, max_lines=1)}", fontsize=7.6, line_gap=9, color=(0.38, 0.30, 0.24))
            state["y"] = top + 88

    @staticmethod
    def _confidence_label(value: float, *, chinese: bool) -> str:
        if value >= 0.8:
            return "高" if chinese else "High"
        if value >= 0.6:
            return "中" if chinese else "Medium"
        return "低" if chinese else "Low"

    def _evidence_ledger_cards(self, state, ensure, report: SurveyReport, *, chinese: bool) -> None:
        for item in report.evidence_appendix:
            ensure(96)
            top = state["y"]
            page = state["page"]
            right = page.rect.width - self.layout.right_margin
            page.draw_rect((self.layout.left_margin, top - 8, right, top + 78), color=(0.84, 0.87, 0.88), fill=(0.985, 0.988, 0.99), width=0.5)
            status = self._status(item.support_status.value, chinese=chinese)
            location = f"第 {item.page} 页" if chinese and item.page else (f"p.{item.page}" if item.page else ("位置不可用" if chinese else "Location unavailable"))
            confidence = self._confidence_label(item.confidence, chinese=chinese)
            header = (f"[{item.citation_number}]  {status}  ·  证据强度 {confidence}  ·  {location}" if chinese else f"[{item.citation_number}]  {status}  ·  Evidence strength {confidence}  ·  {location}")
            self._insert_text(page, (self.layout.left_margin + 8, top + 8), header, fontsize=7.4, color=(0.04, 0.35, 0.36))
            statement = self._limited_lines(item.statement_text, max_chars=96, max_lines=2)
            self._insert_text_lines(page, self.layout.left_margin + 8, top + 25, statement, fontsize=8.1, line_gap=10.5, color=(0.10, 0.14, 0.17))
            quote_label = "原文：" if chinese else "Quote: "
            quote = self._limited_lines(quote_label + item.quote, max_chars=108, max_lines=2)
            self._insert_text_lines(page, self.layout.left_margin + 8, top + 52, quote, fontsize=7, line_gap=9, color=(0.37, 0.40, 0.42))
            state["y"] = top + 90
    def _summary_cards(self, state, ensure, report: SurveyReport, page_rect, *, chinese: bool) -> None:
        """Draw compact evidence-volume cards on the cover page."""

        years = [item.year for item in report.literature_timeline if item.year is not None]
        year_value = f"{min(years)}—{max(years)}" if years else ("未知" if chinese else "N/A")
        requested_start = report.metadata.get("requested_start_year")
        requested_end = report.metadata.get("requested_end_year")
        requested_value = f"{requested_start}—{requested_end}" if requested_start and requested_end else ("未限定" if chinese else "Not set")
        cards = [
            ("核心文献" if chinese else "Core papers", str(len(report.references))),
            ("已验证证据" if chinese else "Verified evidence", str(len(report.evidence_appendix))),
            ("请求范围" if chinese else "Requested span", requested_value),
            ("实际覆盖" if chinese else "Included span", year_value),
        ]
        left = self.layout.left_margin
        available = page_rect.width - self.layout.left_margin - self.layout.right_margin
        gap = 8
        width = (available - gap * 3) / 4
        height = 52
        ensure(height + 12)
        for index, (label, value) in enumerate(cards):
            x0 = left + index * (width + gap)
            rect = (x0, state["y"], x0 + width, state["y"] + height)
            state["page"].draw_rect(
                rect,
                color=(0.82, 0.87, 0.89),
                fill=(0.96, 0.98, 0.98),
                width=0.6,
            )
            self._insert_text(
                state["page"],
                (x0 + 8, state["y"] + 18),
                label,
                fontsize=7.6,
                color=(0.35, 0.42, 0.46),
            )
            self._insert_text(
                state["page"],
                (x0 + 8, state["y"] + 38),
                value,
                fontsize=11.5,
                color=(0.04, 0.28, 0.35),
            )
        state["y"] += height + 18

    def _comparison_text(self, state, ensure, report: SurveyReport, *, chinese: bool) -> None:
        matrix = report.comparison_matrix or {}
        columns, rows = matrix.get("columns", []), matrix.get("rows", [])
        if not columns or not rows:
            message = "缺少可直接比较的已验证信息" if chinese else "Insufficient information for direct comparison"
            self._insert_text(state["page"], (self.layout.left_margin, state["y"]), message, fontsize=self.layout.body_size)
            state["y"] += 18
            return
        self._comparison_matrix_table(state, ensure, report, rows, chinese=chinese)
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

    def _comparison_matrix_table(self, state, ensure, report, rows, *, chinese: bool) -> None:
        """Render a compact cross-paper matrix with explicit evidence gaps."""

        widths = [30, 34, 67, 145, 145, 52]
        headers = (["文献", "年份", "方法族", "贡献 / 关键发现", "作者陈述的局限", "证据"] if chinese else ["Ref", "Year", "Family", "Contribution / finding", "Author-stated limitation", "Evidence"])
        left = self.layout.left_margin
        row_height = 62
        header_height = 27
        header_page = -1

        def draw_header() -> None:
            nonlocal header_page
            ensure(header_height + 3)
            page = state["page"]
            top = state["y"]
            x = left
            for width, label in zip(widths, headers):
                page.draw_rect((x, top - 9, x + width, top + header_height - 9), color=(0.63, 0.74, 0.77), fill=(0.08, 0.30, 0.36), width=0.5)
                self._insert_text(page, (x + 4, top + 8), label, fontsize=7, color=(1, 1, 1))
                x += width
            state["y"] = top + header_height
            header_page = state["page_index"]

        draw_header()
        for row_index, row in enumerate(rows):
            ensure(row_height + 2)
            if state["page_index"] != header_page:
                draw_header()
                ensure(row_height + 2)
            page = state["page"]
            top = state["y"]
            cells = row.get("cells", {})
            citation = row.get("citation_number") or cells.get("citation", {}).get("value") or "—"
            year = cells.get("year", {}).get("value") or "—"
            family = cells.get("method_family", {}).get("value")
            family = self._family_name(report, family) if family else ("未分类" if chinese else "Unclassified")
            contribution_cell = cells.get("primary_contribution", {})
            contribution = contribution_cell.get("value")
            if not contribution:
                finding = cells.get("key_findings", {}).get("value")
                if isinstance(finding, list):
                    finding = finding[0] if finding else None
                if finding:
                    contribution = ("关键发现：" if chinese else "Finding: ") + str(finding)
            contribution = contribution or ("未定位到可验证贡献" if chinese else "No verified contribution")
            limitation_cell = cells.get("primary_limitation", {})
            limitation = limitation_cell.get("value")
            limitation = limitation or ("未定位到作者明确陈述的局限" if chinese else "No author-stated limitation")
            evidence = cells.get("evidence_coverage", {}).get("value")
            values = [f"[{citation}]", str(year), str(family), str(contribution), str(limitation), str(evidence if evidence is not None else "—")]
            max_chars = [8, 8, 20, 42, 42, 10]
            max_lines = [1, 1, 3, 3, 3, 1]
            x = left
            fill = (0.975, 0.985, 0.985) if row_index % 2 == 0 else (1, 1, 1)
            for width, value, chars, lines in zip(widths, values, max_chars, max_lines):
                page.draw_rect((x, top - 9, x + width, top + row_height - 9), color=(0.79, 0.84, 0.86), fill=fill, width=0.45)
                rendered = self._limited_lines(value, max_chars=chars, max_lines=lines)
                self._insert_text_lines(page, x + 4, top + 10, rendered, fontsize=6.8, line_gap=10, color=(0.10, 0.15, 0.18))
                x += width
            state["y"] = top + row_height
        state["y"] += 8
    def _comparison_cards(self, state, ensure, report, rows, *, chinese: bool) -> None:
        """Render one readable comparison card per paper instead of pipe text."""

        detail_columns = [
            "primary_contribution",
            "dataset",
            "metric",
            "reported_result",
            "primary_limitation",
        ]
        for row in rows:
            cells = row.get("cells", {})
            citation = row.get("citation_number") or cells.get("citation", {}).get("value") or "?"
            year = cells.get("year", {}).get("value") or ("年份未知" if chinese else "Year unavailable")
            family = cells.get("method_family", {}).get("value")
            if family is not None:
                family = self._family_name(report, family)
            family = family or ("未分类" if chinese else "Unclassified")
            # Reserve the complete card before drawing its header so a paper
            # never continues anonymously on the following page.
            estimated_lines = 0
            for column in detail_columns:
                value = cells.get(column, {}).get("value")
                if isinstance(value, list):
                    value = "; ".join(map(str, value))
                if cells.get(column, {}).get("notes") == "NO_VERIFIED_LIMITATION":
                    value = "暂无已验证的局限性证据" if chinese else "No verified limitation evidence"
                if value not in (None, ""):
                    label = self._column_label(column, chinese=chinese)
                    estimated_lines += len(self._wrap(f"{label}: {value}", max_chars=105))
            ensure(34 + estimated_lines * (8.5 * 1.4 + 3))
            top = state["y"]
            state["page"].draw_rect(
                (
                    self.layout.left_margin,
                    top - 10,
                    state["page"].rect.width - self.layout.right_margin,
                    top + 15,
                ),
                color=(0.78, 0.86, 0.88),
                fill=(0.94, 0.97, 0.97),
                width=0.5,
            )
            heading = (
                f"论文 [{citation}]  ·  {year}  ·  {family}"
                if chinese
                else f"Paper [{citation}]  ·  {year}  ·  {family}"
            )
            self._insert_text(
                state["page"],
                (self.layout.left_margin + 8, top + 6),
                heading,
                fontsize=9,
                color=(0.04, 0.28, 0.35),
            )
            state["y"] = top + 24
            for column in detail_columns:
                cell = cells.get(column, {})
                value = cell.get("value")
                if isinstance(value, list):
                    value = "; ".join(map(str, value))
                if cell.get("notes") == "NO_VERIFIED_LIMITATION":
                    value = "暂无已验证的局限性证据" if chinese else "No verified limitation evidence"
                if value in (None, ""):
                    continue
                label = self._column_label(column, chinese=chinese)
                self._write_lines(state, ensure, f"{label}: {value}", size=8.5)
            state["y"] += 5

    def _taxonomy_overview(self, state, ensure, report: SurveyReport, *, chinese: bool) -> None:
        """Render the method-family structure as a technical landscape."""

        families = report.taxonomy_summary.get("families", [])
        for family in families:
            members = family.get("member_citation_numbers") or []
            mechanism = family.get("common_mechanism") or family.get("description") or ""
            advantages = "；".join(family.get("advantages") or [])
            limitations = "；".join(family.get("limitations") or [])
            estimated = 46
            estimated += 12 * len(self._wrap(str(mechanism), max_chars=98))
            estimated += 12 * len(self._wrap(str(advantages), max_chars=98))
            estimated += 12 * len(self._wrap(str(limitations), max_chars=98))
            ensure(estimated)
            top = state["y"]
            state["page"].draw_rect(
                (
                    self.layout.left_margin,
                    top - 8,
                    state["page"].rect.width - self.layout.right_margin,
                    top + 15,
                ),
                color=(0.78, 0.86, 0.88),
                fill=(0.94, 0.97, 0.97),
                width=0.5,
            )
            name = family.get("name") or ("未分类" if chinese else "Unclassified")
            member_text = "、".join(f"[{value}]" for value in members)
            self._insert_text(
                state["page"],
                (self.layout.left_margin + 8, top + 6),
                f"{name}  ·  {member_text}",
                fontsize=9.2,
                color=(0.04, 0.28, 0.35),
            )
            state["y"] = top + 24
            labels = (
                (("共同机制", mechanism), ("主要优势", advantages), ("关键边界", limitations))
                if chinese
                else (("Mechanism", mechanism), ("Strengths", advantages), ("Boundaries", limitations))
            )
            for label, value in labels:
                if value:
                    self._write_lines(state, ensure, f"{label}: {value}", size=8.5)
            state["y"] += 5

    def _method_spotlight(self, state, ensure, report: SurveyReport, *, chinese: bool) -> None:
        """Add one evidence-linked system deep dive when Cartographer is present."""

        profile = next(
            (
                item
                for item in report.core_paper_profiles
                if "cartographer" in (
                    str(item.get("title", ""))
                    + " "
                    + str(item.get("method_summary", ""))
                ).casefold()
            ),
            None,
        )
        if profile is None:
            return
        ensure(150)
        title = "代表方法深挖：Cartographer" if chinese else "Method spotlight: Cartographer"
        self._insert_text(
            state["page"],
            (self.layout.left_margin, state["y"]),
            title,
            fontsize=11.5,
            color=(0.04, 0.28, 0.35),
        )
        state["y"] += 20
        contribution = profile.get("primary_contribution") or {}
        additional = profile.get("additional_contributions") or []
        advantage = additional[0] if additional else contribution
        limitation = profile.get("primary_limitation") or {}
        lines = (
            (
                "系统机制",
                profile.get("method_summary") or contribution.get("text") or "",
            ),
            ("核心价值", advantage.get("text") or contribution.get("text") or ""),
            ("工程边界", limitation.get("text") or ""),
            (
                "证据覆盖",
                f"{profile.get('verified_evidence_count', 0)} 条已验证证据",
            ),
        )
        for label, value in lines:
            if value:
                self._write_lines(state, ensure, f"{label}: {value}", size=9)
        state["y"] += 6

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

    @staticmethod
    def _timeline_page_groups(entries, page_size: int = 4):
        """Keep timeline cards readable on A4 instead of squeezing ten nodes together."""

        ordered = sorted(
            entries,
            key=lambda item: (
                item.year is None,
                item.year or 0,
                item.authors_short.casefold(),
                item.short_title.casefold(),
                item.citation_number,
            ),
        )
        return [ordered[index : index + page_size] for index in range(0, len(ordered), page_size)]

    def _fishbone_page(self, document, entries, page_rect, figure_number: int, figure_total: int, *, chinese: bool) -> None:
        page = document.new_page(width=page_rect.width, height=page_rect.height)
        caption = "图 1——核心文献时间线演化" if chinese else "Figure 1 - Timeline evolution of core literature"
        page.draw_rect(page.rect, color=(0.965, 0.976, 0.982), fill=(0.965, 0.976, 0.982), overlay=True)
        self._insert_text(page, (self.layout.left_margin, self.layout.top_margin), caption, fontsize=15, color=(0.04, 0.20, 0.28))
        entries = list(entries)
        years = [entry.year for entry in entries if entry.year is not None]
        year_range = f"{min(years)}-{max(years)}" if years else ("年份未知" if chinese else "Years unavailable")
        subtitle = (
            f"第 {figure_number}/{figure_total} 页 · {year_range} · 按发表时间排序 · 点击来源可访问原文"
            if chinese
            else f"Page {figure_number} of {figure_total} · {year_range} · Chronological order · Sources are clickable"
        )
        self._insert_text(page, (self.layout.left_margin, self.layout.top_margin + 23), subtitle, fontsize=8.5, color=(0.35, 0.43, 0.48))
        left = self.layout.left_margin
        spine_x = page_rect.width / 2
        page.draw_line((spine_x, 132), (spine_x, 745), color=(0.15, 0.48, 0.52), width=2)
        if not entries:
            message = "暂无足够的核心文献时间线数据。" if chinese else "No sufficient core literature timeline data."
            self._insert_text(page, (left, page_rect.height / 2), message, fontsize=9)
            return

        card_width = 210
        card_height = 156
        card_gap = 24
        y_positions = [165, 350, 535, 720]
        for index, entry in enumerate(entries):
            y = y_positions[index]
            on_left = index % 2 == 0
            card_left = spine_x - card_gap - card_width if on_left else spine_x + card_gap
            rect_type = type(page.rect)
            card_rect = rect_type(card_left, y - card_height / 2, card_left + card_width, y + card_height / 2)
            page.draw_rect(card_rect, color=(0.82, 0.87, 0.89), fill=(1, 1, 1), width=0.7, overlay=True)
            accent_x = card_rect.x0 if on_left else card_rect.x1 - 4
            page.draw_rect(
                rect_type(accent_x, card_rect.y0, accent_x + 4, card_rect.y1),
                color=(0.05, 0.45, 0.42),
                fill=(0.05, 0.45, 0.42),
                overlay=True,
            )
            connector_start = card_rect.x1 if on_left else card_rect.x0
            page.draw_line((connector_start, y), (spine_x, y), color=(0.38, 0.58, 0.61), width=1)
            page.draw_circle((spine_x, y), 5, color=(1, 1, 1), fill=(0.05, 0.45, 0.42), width=1.4)

            year = str(entry.year) if entry.year is not None else ("年份未知" if chinese else "Year unavailable")
            title = self._limited_lines(entry.short_title, max_chars=48, max_lines=2)
            contribution_missing = "未定位到可验证的贡献；请查看原文与证据台账" if chinese else "No verified contribution located; review the source and evidence ledger"
            limitation_missing = "原文未明确陈述局限；系统不作推断" if chinese else "No author-stated limitation located; no inference was made"
            contribution = self._limited_lines(entry.primary_contribution or contribution_missing, max_chars=46, max_lines=2)
            limitation = self._limited_lines(entry.primary_limitation or limitation_missing, max_chars=46, max_lines=2)
            contribution_label = (
                "关键发现"
                if chinese and entry.contribution_kind == "key_finding"
                else "摘要要点"
                if chinese and entry.contribution_kind == "abstract_summary"
                else "贡献"
                if chinese
                else "KEY FINDING"
                if entry.contribution_kind == "key_finding"
                else "ABSTRACT HIGHLIGHT"
                if entry.contribution_kind == "abstract_summary"
                else "Contribution:"
            )
            source_text, source_url = self._timeline_source(entry, chinese=chinese)
            text_left = card_rect.x0 + 13
            self._insert_text(page, (text_left, card_rect.y0 + 18), f"{year}  ·  [{entry.citation_number}]", fontsize=8.5, color=(0.03, 0.37, 0.39))
            self._insert_text_lines(page, text_left, card_rect.y0 + 38, title, fontsize=8.2, line_gap=10.5, color=(0.07, 0.12, 0.16))
            source_y = card_rect.y0 + 67
            self._insert_text(page, (text_left, source_y), source_text, fontsize=6.6, color=(0.08, 0.35, 0.55))
            if source_url:
                page.insert_link({"kind": 2, "from": rect_type(text_left, source_y - 8, card_rect.x1 - 11, source_y + 3), "uri": source_url})
            self._insert_text(page, (text_left, card_rect.y0 + 83), contribution_label, fontsize=6.7, color=(0.05, 0.45, 0.42))
            self._insert_text_lines(page, text_left, card_rect.y0 + 97, contribution, fontsize=7.1, line_gap=9.3, color=(0.24, 0.29, 0.32))
            self._insert_text(page, (text_left, card_rect.y0 + 123), "局限" if chinese else "Limitation:", fontsize=6.7, color=(0.68, 0.38, 0.12))
            self._insert_text_lines(page, text_left, card_rect.y0 + 137, limitation, fontsize=7.1, line_gap=9.3, color=(0.30, 0.30, 0.30))

        legend = "● 核心文献节点    内容来自摘要/全文证据；缺失项不作推断" if chinese else "● Core paper node    Content is evidence-linked; missing claims are not inferred"
        self._insert_text(page, (left, page_rect.height - 48), legend, fontsize=7.5, color=(0.38, 0.44, 0.47))

    @staticmethod
    def _timeline_source(entry, *, chinese: bool) -> tuple[str, str | None]:
        prefix = "来源：" if chinese else "Source: "
        if entry.arxiv_id:
            return f"{prefix}arXiv {entry.arxiv_id}", entry.source_url or f"https://arxiv.org/abs/{entry.arxiv_id}"
        if entry.doi:
            return f"{prefix}DOI {entry.doi}", entry.source_url or f"https://doi.org/{entry.doi}"
        if entry.source_url:
            return f"{prefix}{SurveyPdfRenderer._truncate(entry.source_url, 38)}", entry.source_url
        return (f"{prefix}元数据记录（链接不可用）" if chinese else f"{prefix}metadata record (link unavailable)"), None

    def _insert_text_lines(self, page, x: float, first_baseline: float, text: str, *, fontsize: float, line_gap: float, color) -> None:
        for index, line in enumerate(str(text).splitlines()):
            self._insert_text(page, (x, first_baseline + index * line_gap), line, fontsize=fontsize, color=color)
    @classmethod
    def _limited_lines(cls, text: str, *, max_chars: int, max_lines: int) -> str:
        lines = cls._wrap(text, max_chars=max_chars)
        if len(lines) <= max_lines:
            return "\n".join(lines)
        visible = lines[:max_lines]
        visible[-1] = visible[-1].rstrip("…") + "…"
        return "\n".join(visible)
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
        running_title = report.title.split("：", 1)[0].split(":", 1)[0]
        self._insert_text(page, (self.layout.left_margin, 28), self._truncate(running_title, 46), fontsize=8, color=(0.25, 0.3, 0.35))

    def _preview_watermark(self, page, *, chinese: bool = False) -> None:
        """Mark preview pages so synthetic demo output is never read as a real survey."""

        label = (
            "预览样张——合成数据，不可作为真实引用"
            if chinese
            else "PREVIEW - synthetic data, not citable"
        )
        self._insert_text(
            page,
            (self.layout.left_margin, page.rect.height / 2),
            label,
            fontsize=18,
            color=(0.86, 0.88, 0.91),
        )

    def _footer(self, page, number: int, total: int, *, chinese: bool = False) -> None:
        label = "PaperGuide AI——证据驱动技术综述" if chinese else "PaperGuide AI - Evidence-grounded survey"
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

    def _insert_textbox(self, page, rect, text: str, **kwargs) -> float:
        if not re.search(r"[\u3400-\u9fff]", text):
            return page.insert_textbox(rect, text, fontname=self._FONT, **kwargs)
        return page.insert_textbox(
            rect,
            text,
            fontname=self._CJK_FONT,
            fontfile=str(self.font_resolver.resolve()),
            **kwargs,
        )
    @staticmethod
    def _is_chinese(report: SurveyReport) -> bool:
        """Use the planned intent locale rather than rendered-text heuristics."""

        return report.query_language == "zh"
