import re

from paperguide.reporting import TimelineFishboneRenderer
from tests.test_survey_synthesis import make_fixture


def test_empty_timeline_returns_no_figure():
    assert TimelineFishboneRenderer().render([]) == ""


def test_fishbone_is_safe_vector_and_deterministic():
    _, evidence, _ = make_fixture()
    renderer = TimelineFishboneRenderer()
    first = renderer.render(evidence.literature_timeline)
    second = renderer.render(evidence.literature_timeline)
    assert first == second
    assert first.startswith("<svg") and "viewBox=" in first
    assert "<script" not in first and "foreignObject" not in first and "href=" not in first
    assert "Contribution:" in first and "Limitation:" in first


def test_fishbone_unknown_year_and_malicious_text_escaped():
    _, evidence, _ = make_fixture()
    item = evidence.literature_timeline[0].model_copy(update={"year": None, "short_title": "</text><script>alert(1)</script>"})
    svg = TimelineFishboneRenderer().render([item])
    assert "&lt;/text&gt;" in svg
    assert "<script>" not in svg
    assert "Year unavailable" in svg


def test_large_timeline_is_split_without_random_ids():
    _, evidence, _ = make_fixture()
    entries = list(evidence.literature_timeline) * 4
    groups = TimelineFishboneRenderer().render_groups(entries)
    assert len(groups) >= 2
    assert all("uuid" not in item.casefold() for item in groups)
