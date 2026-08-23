"""Regression coverage for deterministic Survey presentation locale handling."""

from io import BytesIO

import pymupdf
from pypdf import PdfReader

from paperpilot.relevance import ReportMode
from paperpilot.reporting import (
    FullSurveySynthesisService,
    SurveyMarkdownRenderer,
    SurveyPdfRenderer,
    SurveySynthesisWriter,
)
from tests.test_survey_synthesis import FakeChineseStageLLM, FakeStageLLM, make_fixture


QUESTION = "目标检测与视觉 SLAM 融合研究进展"


def _report(mode: ReportMode, *, chinese: bool):
    context, evidence, analysis = make_fixture(mode)
    if chinese:
        context = context.model_copy(
            update={"research_question": QUESTION, "query_language": "zh"}
        )
        writer = FakeChineseStageLLM()
    else:
        writer = FakeStageLLM()
    return FullSurveySynthesisService(SurveySynthesisWriter(writer)).generate(
        context, evidence, analysis
    )


def _pdf_text(report) -> tuple[bytes, str]:
    payload = SurveyPdfRenderer().render(report)
    document = pymupdf.open(stream=payload, filetype="pdf")
    try:
        return payload, "\n".join(page.get_text() for page in document)
    finally:
        document.close()


def test_limited_chinese_report_keeps_title_abstract_and_headings_intact() -> None:
    report = _report(ReportMode.EVIDENCE_LIMITED_REVIEW, chinese=True)
    payload, text = _pdf_text(report)
    assert report.query_language == "zh"
    assert "SLAM 研究综述" in report.title
    assert QUESTION in report.abstract
    assert report.title.endswith("证据评估")
    assert all(label in report.abstract for label in ("背景：", "方法：", "结果：", "局限："))
    assert all(any("\u4e00" <= char <= "\u9fff" for char in section.title) for section in report.sections)
    assert "SLAM" in text.replace("\xa0", " ")
    assert "摘要" in text and "研究背景与关键技术" in text and "未来研究方向" in text
    assert "?" not in report.title
    assert payload.startswith(b"%PDF-")


def test_full_chinese_report_uses_embedded_cjk_font_for_visible_text() -> None:
    report = _report(ReportMode.FULL_SURVEY, chinese=True)
    payload, text = _pdf_text(report)
    assert "技术分类体系" in text
    assert "按方法族组织的研究进展" in text
    reader = PdfReader(BytesIO(payload))
    embedded = False
    for page in reader.pages:
        for reference in page.get("/Resources", {}).get("/Font", {}).values():
            font = reference.get_object()
            for descendant in font.get("/DescendantFonts") or []:
                descriptor = descendant.get_object().get("/FontDescriptor")
                descriptor = descriptor.get_object() if descriptor else None
                embedded = embedded or bool(
                    descriptor
                    and any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
                )
    assert embedded


def test_english_report_remains_english() -> None:
    report = _report(ReportMode.FULL_SURVEY, chinese=False)
    markdown = SurveyMarkdownRenderer().render(report)
    assert report.query_language == "en"
    assert "Abstract" in markdown
    assert "## 10 Conclusion" in markdown
