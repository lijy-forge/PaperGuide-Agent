"""The evaluation harness is itself testable: the demo tier must stay offline."""

from evals.paperguide.checks import INVARIANTS, METRICS, citation_density
from evals.paperguide.runner import CaseResult, run_demo_case, run_retrieval_case


def test_demo_tier_case_passes_every_invariant_offline():
    result = run_demo_case(
        {
            "id": "harness-demo",
            "question": "视觉SLAM回环检测综述",
            "max_papers": 3,
            "expect": {"status": "completed"},
            "invariants": list(INVARIANTS),
        }
    )
    assert result.passed, result.failures
    assert set(result.invariants) == set(INVARIANTS)
    assert set(result.metrics) == set(METRICS)


def test_offtopic_question_is_reported_as_out_of_scope():
    result = run_demo_case(
        {
            "id": "harness-offtopic",
            "question": "分析屈服值预测相关的论文",
            "max_papers": 3,
            "expect": {"warnings_contain": ["与本次提问主题无关"]},
            "invariants": [],
        }
    )
    assert result.passed, result.failures


def test_retrieval_tier_skips_instead_of_reaching_the_network_unlabelled():
    result = run_retrieval_case(
        {"id": "harness-retrieval", "question": "x", "ground_truth": []}
    )
    assert result.skipped
    assert result.duration_ms == 0.0


def test_citation_density_counts_distinct_references_not_tokens():
    class _Paragraph:
        citation_refs = ["[1,2,3]"]

    class _Section:
        paragraphs = [_Paragraph()]

    class _Report:
        sections = [_Section()]

    # One ref string naming three references scores 3, not 1, and a page
    # locator must not be mistaken for a reference number.
    assert citation_density(_Report()) == 3.0
    _Paragraph.citation_refs = ["[4, p.7]"]
    assert citation_density(_Report()) == 1.0



def test_a_skipped_run_is_refused_as_a_baseline():
    """A skipped case measured nothing, so it must not become the reference."""

    from evals.paperguide.__main__ import storable

    measured = CaseResult(case_id="a", tier="retrieval", passed=True, duration_ms=1.0)
    outage = CaseResult(
        case_id="b", tier="retrieval", passed=True, duration_ms=1.0, skipped="no source answered"
    )

    assert storable([measured])
    assert not storable([measured, outage])
    assert not storable([])


def test_a_partial_outage_is_refused_as_a_baseline():
    """A case that measured a smaller pool must not become the reference.

    This is the dangerous one: unlike a skip it reports a plausible number, so
    committing it looks harmless and then makes the next healthy run read as an
    improvement that never happened.
    """

    from evals.paperguide.__main__ import storable

    degraded = CaseResult(
        case_id="c",
        tier="retrieval",
        passed=True,
        duration_ms=1.0,
        metrics={"recall_at_20": 0.2},
        degraded="only 2/3 sources answered: {'arxiv': 'HTTP Error 406'}",
    )

    assert not storable([degraded])


def test_the_report_marks_a_degraded_case():
    """A number produced under an outage has to be visible as one."""

    from evals.paperguide.report import to_markdown

    degraded = CaseResult(
        case_id="c",
        tier="retrieval",
        passed=True,
        duration_ms=1.0,
        metrics={"recall_at_20": 0.2},
        degraded="only 2/3 sources answered",
    )

    markdown = to_markdown([degraded])
    assert "degraded" in markdown
    assert "not fit for a baseline" in markdown


def test_the_baseline_path_defaults_to_the_committed_directory():
    from evals.paperguide.__main__ import BASELINES_DIR, _baseline_path

    assert _baseline_path("demo", None) == BASELINES_DIR / "demo.json"
    assert _baseline_path("demo", "/tmp/other.json").name == "other.json"
    # Without a tier there is no single baseline to compare against.
    assert _baseline_path(None, None) is None


def test_the_decision_tier_separates_labelled_papers():
    """The gate must score the positives above the negatives.

    Separation is the metric that can fail silently: a gate that rejected or
    admitted everything would still report a false-core rate of 0.
    """

    from pathlib import Path

    import yaml
    from evals.paperguide.runner import run_decision_case

    case = yaml.safe_load(
        (
            Path(__file__).parent.parent
            / "evals/paperguide/cases/decision/visual-slam-dynamic-semantic.yaml"
        ).read_text("utf-8")
    )
    result = run_decision_case(case)

    assert result.passed, result.failures
    assert result.metrics["score_separation"] > 0
    assert result.metrics["positive_mean_score"] > result.metrics["negative_mean_score"]


def test_a_decision_case_needs_both_groups():
    """Only one group cannot show whether the gate discriminates."""

    from evals.paperguide.runner import run_decision_case

    result = run_decision_case(
        {"id": "x", "question": "q", "positives": ["A Paper"], "negatives": []}
    )
    assert result.skipped


def test_decision_candidates_carry_identical_metadata():
    """Both groups must be handicapped the same, or the gap measures metadata."""

    from evals.paperguide.runner import _decision_candidate

    first = _decision_candidate("A Title")
    second = _decision_candidate("Another Title Entirely")
    assert first.publication_year is second.publication_year is None
    assert first.abstract is second.abstract is None
    assert first.venue is second.venue is None
