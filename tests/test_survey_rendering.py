import re

from paperguide.reporting import (
    FullSurveySynthesisService,
    SurveyHtmlRenderer,
    SurveyMarkdownRenderer,
    SurveyRenderFormat,
    SurveyRenderService,
    SurveySynthesisWriter,
)

from tests.test_survey_synthesis import FakeChineseStageLLM, FakeStageLLM, make_fixture


def make_report(mode=None):
    context, evidence, analysis = make_fixture(mode) if mode else make_fixture()
    return FullSurveySynthesisService(SurveySynthesisWriter(FakeStageLLM())).generate(context, evidence, analysis)


def make_chinese_report():
    context, evidence, analysis = make_fixture()
    context = context.model_copy(update={"research_question": "目标检测与视觉 SLAM 融合研究进展", "query_language": "zh"})
    return FullSurveySynthesisService(SurveySynthesisWriter(FakeChineseStageLLM())).generate(context, evidence, analysis)


def test_markdown_full_structure_and_determinism():
    report = make_report()
    renderer = SurveyMarkdownRenderer()
    first, second = renderer.render(report), renderer.render(report)
    assert first == second
    assert first.startswith("# ")
    assert "## 10 Conclusion" in first
    assert "## References" in first
    assert "## Appendix A" in first and "## Appendix B" in first
    assert "statement_key" not in first
    assert "paper_id" not in first


def test_markdown_has_comparison_and_timeline_fallback():
    text = SurveyMarkdownRenderer().render(make_report())
    assert "Comparison Matrix" in text
    assert "Literature timeline" in text
    assert "| Year | Citation | Paper |" in text
    assert "NO_VERIFIED_LIMITATION" not in text


def test_limited_markdown_has_scope_note_without_full_structure():
    from paperguide.relevance import ReportMode
    text = SurveyMarkdownRenderer().render(make_report(ReportMode.EVIDENCE_LIMITED_REVIEW))
    assert "Evidence-limited review" in text
    assert "## 10 Conclusion" in text
    assert "## 5 Research Progress" not in text


def test_html_semantic_structure_toc_and_escaping():
    report = make_report()
    report = report.model_copy(update={"title": "<script>alert(1)</script>"})
    text = SurveyHtmlRenderer().render(report)
    assert "<article class=\"survey-report\">" in text
    assert "<nav class=\"toc\">" in text
    assert "<section" in text and "<figure" in text and "<table" in text
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "Content-Security-Policy" in text
    assert "https://" not in text
    assert "statement_key" not in text
    assert "paper_id" not in text


def test_html_is_deterministic_and_responsive():
    renderer = SurveyHtmlRenderer()
    first, second = renderer.render(make_report()), renderer.render(make_report())
    # Internal identifiers never reach the public HTML, so two renders of an
    # equivalent report are byte-identical.
    assert first == second
    assert "#section-1" in first and "#section-10" in first
    assert "@media(max-width:700px)" in first
    assert re.search(r"<meta name=\"viewport\"", first)


def test_render_service_formats():
    report = make_report()
    service = SurveyRenderService()
    markdown = service.render(report, SurveyRenderFormat.MARKDOWN)
    html = service.render(report, SurveyRenderFormat.HTML)
    assert markdown.extension == ".md" and markdown.mime_type.startswith("text/markdown")
    assert html.extension == ".html" and html.mime_type.startswith("text/html")


def test_chinese_markdown_localizes_presentation_labels():
    text = SurveyMarkdownRenderer().render(make_chinese_report())
    assert "## 参考文献" in text
    assert "## 附录 A——核心论文概览" in text
    assert "| 年份 | 引用 | 论文 | 主要贡献 | 主要局限 |" in text
    assert "## References" not in text


def test_chinese_html_localizes_presentation_labels():
    text = SurveyHtmlRenderer().render(make_chinese_report())
    assert '<html lang="zh">' in text
    assert "<h2>目录</h2>" in text
    assert "<h2>参考文献</h2>" in text
    assert "附录 A——核心论文概览" in text
    assert ">References<" not in text
