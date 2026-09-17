"""The evaluation harness is itself testable: the demo tier must stay offline."""

from evals.paperguide.checks import INVARIANTS, METRICS, citation_density
from evals.paperguide.runner import run_demo_case, run_retrieval_case


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
