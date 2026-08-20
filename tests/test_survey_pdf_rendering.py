import re

import pymupdf
from pypdf import PdfReader
from io import BytesIO

from paperpilot.reporting import CJKFontResolver, SurveyPdfRenderer, SurveyRenderFormat, SurveyRenderService
from tests.test_survey_rendering import make_report
from tests.test_survey_synthesis import FakeChineseStageLLM, make_fixture
from paperpilot.reporting import FullSurveySynthesisService, SurveySynthesisWriter


def test_pdf_is_valid_a4_and_has_metadata():
    report = make_report()
    payload = SurveyPdfRenderer().render(report)
    assert payload.startswith(b"%PDF")
    document = pymupdf.open(stream=payload, filetype="pdf")
    assert document.page_count >= 1
    assert all(abs(page.rect.width - 595) < 2 and abs(page.rect.height - 842) < 2 for page in document)
    metadata = document.metadata
    assert metadata["title"] == report.title
    text = "\n".join(page.get_text() for page in document)
    assert "References" in text and "Appendix A" in text and "Appendix B" in text
    assert "statement_key" not in text and "paper_id" not in text and "SLOT_ONLY" not in text
    document.close()


def test_pdf_contains_fishbone_and_comparison_data():
    report = make_report()
    payload = SurveyPdfRenderer().render(report)
    document = pymupdf.open(stream=payload, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    assert "Figure 1" in text
    assert "Contribution:" in text
    assert "Comparison" in text or "comparison" in text
    assert "No verified limitation evidence" in text
    document.close()


def test_pdf_limited_mode_and_render_service():
    from paperpilot.relevance import ReportMode
    report = make_report(ReportMode.EVIDENCE_LIMITED_REVIEW)
    result = SurveyRenderService().render(report, SurveyRenderFormat.PDF)
    assert result.mime_type == "application/pdf" and result.extension == ".pdf"
    assert bytes(result.content).startswith(b"%PDF")


def test_pdf_splits_more_than_ten_fishbone_entries_across_pages():
    report = make_report()
    timeline = [entry.model_copy(update={"citation_number": index + 1}) for index, entry in enumerate(report.literature_timeline)]
    timeline = timeline * 4
    timeline = [entry.model_copy(update={"citation_number": index + 1}) for index, entry in enumerate(timeline[:12])]
    report = report.model_copy(update={"literature_timeline": timeline})
    document = pymupdf.open(stream=SurveyPdfRenderer().render(report), filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    assert document.page_count >= 6
    assert text.count("Figure 1 - Timeline evolution of core literature") >= 2
    assert all(f"[{index}]" in text for index in range(1, 13))
    document.close()


def test_chinese_pdf_uses_localized_labels_and_preserves_paper_titles():
    context, evidence, analysis = make_fixture()
    context = context.model_copy(update={"research_question": "目标检测与视觉 SLAM 融合研究进展", "query_language": "zh"})
    report = FullSurveySynthesisService(SurveySynthesisWriter(FakeChineseStageLLM())).generate(context, evidence, analysis)
    payload = SurveyPdfRenderer().render(report)
    document = pymupdf.open(stream=payload, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    assert "摘要" in text
    assert "参考文献" in text
    assert "附录A" in text.replace(" ", "") and "附录B" in text.replace(" ", "")
    assert report.references[0].title in text
    assert "Evidence-grounded survey" not in text
    document.close()


def test_mixed_cjk_latin_pdf_embeds_real_font_and_extracts_complete_text():
    report = make_report().model_copy(
        update={
            "title": "视觉 SLAM 重定位研究综述 2010-2026",
            "abstract": "中文标题与 English SLAM、数字 2010-2026、标点，以及引用 [1, p.6]。",
        }
    )
    payload = SurveyPdfRenderer().render(report)
    document = pymupdf.open(stream=payload, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    document.close()
    normalized = text.replace("\xa0", " ")
    compact = normalized.replace(" ", "")
    assert "视觉 SLAM 重定位研究综述 2010-2026" in normalized
    assert "中文标题与EnglishSLAM" in compact
    assert "[1,p.6]" in compact

    reader = PdfReader(BytesIO(payload))
    embedded_cjk = False
    for page in reader.pages:
        for reference in page.get("/Resources", {}).get("/Font", {}).values():
            font = reference.get_object()
            descendants = font.get("/DescendantFonts") or []
            candidates = [font] + [item.get_object() for item in descendants]
            for candidate in candidates:
                descriptor = candidate.get("/FontDescriptor")
                descriptor = descriptor.get_object() if descriptor else None
                if descriptor and any(
                    descriptor.get(key) is not None
                    for key in ("/FontFile", "/FontFile2", "/FontFile3")
                ):
                    embedded_cjk = True
    assert embedded_cjk
    assert b"/china-s" not in payload


def test_cjk_font_resolver_returns_installed_font_without_fixed_test_path():
    resolved = CJKFontResolver().resolve()
    assert resolved.is_file()
    assert resolved.suffix.casefold() in {".ttf", ".ttc", ".otf", ".otc"}
