"""Case runners for the two evaluation tiers.

``demo`` runs the whole pipeline against the synthetic corpus. It needs no
credentials and no network, and it is deterministic, so it can gate every
change. It cannot say anything about retrieval quality: the fake retriever
returns the corpus itself, so recall is 1 by construction.

``retrieval`` calls the real arXiv and Semantic Scholar adapters and stops
there. It is the tier that can measure recall. A case supplies the search
queries directly, because retrieval and query planning fail for different
reasons and one number covering both cannot say which of them moved; how well
the planner turns a question into those queries needs its own case. arXiv
needs no key; SEMANTIC_SCHOLAR_API_KEY only raises the rate limit.

``decision`` measures something retrieval cannot: whether the metadata gate
keeps the right papers and drops the wrong ones. Recall only asks what was
found, so a system that retrieves well and then admits everything scores
perfectly on it. The gate is deterministic, so this tier needs no key, no
network and no LLM, and it gives the same answer every time.

Two things are deliberately held fixed, because a number that moves for two
reasons cannot say which one moved:

* The case writes the ``intent`` out in full instead of planning it. In
  production an LLM derives it from the question, so measuring both at once
  would blame the gate for a bad plan. The intent is written from the question
  alone — in particular ``exclusion_concepts`` is left empty unless the
  question itself excludes something, since filling it from the negatives
  would tune the ruler to the answer.
* Every candidate is built from its title only, with no year and no abstract.
  Production feeds the gate abstracts too, so the scores here are lower than
  production's across the board. That is acceptable because both groups are
  handicapped identically, which is what makes positives and negatives
  comparable; it also means an absolute score from this tier says nothing
  about production.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from paperguide.domain import PaperSource, ResearchConfig

from .checks import INVARIANTS, METRICS

CONFIGURED_SOURCES = (
    PaperSource.ARXIV,
    PaperSource.OPENALEX,
    PaperSource.SEMANTIC_SCHOLAR,
)


@dataclass
class CaseResult:
    """Outcome of one evaluated case."""

    case_id: str
    tier: str
    passed: bool
    duration_ms: float
    invariants: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None
    # Measured, but under conditions that make the number unfit to compare
    # against: a source refused, so the candidate pool was smaller than the one
    # the next run will see. The case still reports its recall, because knowing
    # what a halved pool yields is useful; it just must not become a baseline.
    degraded: str | None = None


def _check_expectations(case: dict[str, Any], warnings: list[str], status: str) -> list[str]:
    """Return the unmet ``expect`` clauses of a case."""

    failures: list[str] = []
    expect = case.get("expect") or {}
    if "status" in expect and status != expect["status"]:
        failures.append(f"status is {status}, expected {expect['status']}")
    for fragment in expect.get("warnings_contain") or []:
        if not any(fragment in warning for warning in warnings):
            failures.append(f"no warning contains {fragment!r}")
    for fragment in expect.get("warnings_absent") or []:
        if any(fragment in warning for warning in warnings):
            failures.append(f"a warning unexpectedly contains {fragment!r}")
    return failures


def run_demo_case(case: dict[str, Any]) -> CaseResult:
    """Run one case end to end against the synthetic corpus."""

    from paperguide.application import ResearchRequest
    from paperguide.bootstrap import BootstrapConfig, LLMProviderConfig, PdfDownloadConfig
    from paperguide.demo import create_demo_application

    started = time.monotonic()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        container = create_demo_application(
            BootstrapConfig(
                llm_provider=LLMProviderConfig(provider="demo"),
                model_name="paperguide-offline-demo",
                pdf_download=PdfDownloadConfig(download_directory=root / "downloads"),
                export_directory=root / "artifacts",
            )
        )
        result = container.application_service.run(
            ResearchRequest(
                question=case["question"],
                max_papers=int(case.get("max_papers", 5)),
            )
        )
        report = result.report
        status = result.task.status.value
        warnings = list(report.warnings) if report else []

        invariants: dict[str, bool] = {}
        failures = _check_expectations(case, warnings, status)
        if report is None:
            failures.append("no report was produced")
        else:
            for name in case.get("invariants") or list(INVARIANTS):
                verdict = INVARIANTS[name](report)
                invariants[name] = verdict.passed
                if not verdict.passed:
                    failures.append(f"{name}: {verdict.detail}")

        metrics = {
            name: round(function(report), 4)
            for name, function in METRICS.items()
            if report is not None
        }
        for name, minimum in (case.get("metrics") or {}).items():
            measured = metrics.get(name.removesuffix("_min"))
            if measured is not None and measured < float(minimum):
                failures.append(f"{name}: {measured} < {minimum}")

    return CaseResult(
        case_id=case["id"],
        tier="demo",
        passed=not failures,
        duration_ms=round((time.monotonic() - started) * 1000, 1),
        invariants=invariants,
        metrics=metrics,
        failures=failures,
    )


def _identifiers(paper) -> set[str]:
    """Normalized identifiers a ground-truth entry can match on."""

    found = set()
    if getattr(paper, "arxiv_id", None):
        found.add(f"arxiv:{str(paper.arxiv_id).casefold().removeprefix('arxiv:')}")
    if getattr(paper, "doi", None):
        found.add(f"doi:{str(paper.doi).casefold()}")
    if getattr(paper, "semantic_scholar_id", None):
        found.add(f"s2:{str(paper.semantic_scholar_id).casefold()}")
    return found


def run_retrieval_case(case: dict[str, Any]) -> CaseResult:
    """Measure recall of the real retrievers against a labelled paper set."""

    from paperguide.bootstrap.factory import _default_retrievers
    from paperguide.pipeline import PaperSearchPipeline

    truth = {str(item).casefold() for item in (case.get("ground_truth") or [])}
    if not truth:
        return CaseResult(
            case_id=case["id"],
            tier="retrieval",
            passed=True,
            duration_ms=0.0,
            skipped="ground_truth is empty; label the case to measure recall",
        )

    started = time.monotonic()
    limit = int(case.get("max_papers", 20))
    # In production an LLM planner rewrites the question into English search
    # terms before retrieval — prompts.py requires it — and the deterministic
    # planner does not, it passes the sentence through unchanged. Searching a
    # Chinese question verbatim therefore measures a path the product never
    # takes. A case states its search queries so this tier measures retrieval
    # and ranking; how well the planner produces those queries is a separate
    # question, and mixing the two into one number hides which of them moved.
    queries = [str(item) for item in (case.get("queries") or [])] or [case["question"]]
    search = PaperSearchPipeline(_default_retrievers())

    papers = []
    total_found = 0
    total_after_dedup = 0
    source_errors: dict[str, str] = {}
    for query in queries:
        result = search.search(
            ResearchConfig(
                question=query,
                max_papers=limit,
                sources=list(CONFIGURED_SOURCES),
            )
        )
        papers.extend(result.papers)
        total_found += result.total_found
        total_after_dedup += result.total_after_dedup
        source_errors.update(result.source_errors)

    if not papers and source_errors:
        # Every source refused, so nothing was measured. Reporting that as
        # recall 0 would record a source outage as a retrieval result, and a
        # baseline saved from it would make every later comparison wrong.
        return CaseResult(
            case_id=case["id"],
            tier="retrieval",
            passed=True,
            duration_ms=round((time.monotonic() - started) * 1000, 1),
            skipped=f"no source answered: {source_errors}",
        )

    result = SimpleNamespace(
        papers=papers, total_found=total_found, total_after_dedup=total_after_dedup
    )

    retrieved: set[str] = set()
    for paper in result.papers:
        retrieved |= _identifiers(paper)

    hits = sorted(truth & retrieved)
    misses = sorted(truth - retrieved)
    recall = len(hits) / len(truth)
    metrics = {
        f"recall_at_{limit}": round(recall, 4),
        "total_found": float(result.total_found),
        "after_dedup": float(result.total_after_dedup),
        # A source that refused halves the candidate pool and so halves recall.
        # Without this the drop looks like retrieval got worse.
        "sources_answered": float(len(CONFIGURED_SOURCES) - len(source_errors)),
    }

    # A missed paper is what recall below 1 means, so the threshold decides the
    # verdict and the misses are reported as the diagnosis of it. Failing per
    # miss would make every case red until recall reached 1.
    failures: list[str] = []
    for name, minimum in (case.get("metrics") or {}).items():
        measured = metrics.get(name.removesuffix("_min"))
        if measured is not None and measured < float(minimum):
            failures.append(f"{name}: {measured} < {minimum}")
    notes = [f"missed: {item}" for item in misses]

    # Some sources answered and some refused. Recall was computed over a pool
    # that is missing whatever the refusing source would have contributed, so
    # the figure is real but not comparable: stored as a baseline it would make
    # the next healthy run look like an improvement that never happened.
    degraded = None
    if source_errors:
        answered = len(CONFIGURED_SOURCES) - len(source_errors)
        degraded = (
            f"only {answered}/{len(CONFIGURED_SOURCES)} sources answered: "
            f"{source_errors}"
        )

    return CaseResult(
        case_id=case["id"],
        tier="retrieval",
        passed=not failures,
        duration_ms=round((time.monotonic() - started) * 1000, 1),
        metrics=metrics,
        failures=failures,
        notes=notes,
        degraded=degraded,
    )


def _decision_candidate(title: str):
    """Build a title-only candidate, so both groups carry identical metadata."""

    from paperguide.domain import FullTextStatus, PaperCandidate, PaperSource

    return PaperCandidate(
        title=title,
        normalized_title=" ".join(title.casefold().split()),
        authors=[],
        sources=[PaperSource.ARXIV],
        full_text_status=FullTextStatus.UNAVAILABLE,
    )


def run_decision_case(case: dict[str, Any]) -> CaseResult:
    """Measure whether the metadata gate separates labelled papers correctly."""

    from paperguide.relevance.gate import (
        MetadataRelevanceGate,
    )
    from paperguide.relevance.gate import (
        PreliminaryRelevanceClassification as Verdict,
    )
    from paperguide.relevance.models import ResearchIntent

    positives = [str(item) for item in (case.get("positives") or [])]
    negatives = [str(item) for item in (case.get("negatives") or [])]
    if not positives or not negatives:
        return CaseResult(
            case_id=case["id"],
            tier="decision",
            passed=True,
            duration_ms=0.0,
            skipped="a decision case needs both positives and negatives",
        )

    started = time.monotonic()
    intent = ResearchIntent(
        research_question=case["question"], **(case.get("intent") or {})
    )
    gate = MetadataRelevanceGate()

    def assess(titles: list[str]) -> list[Any]:
        return [gate.assess(_decision_candidate(title), intent) for title in titles]

    positive_results = assess(positives)
    negative_results = assess(negatives)

    # Rejection is the only irreversible verdict: a rejected paper never
    # reaches the evidence stage, so a wrongly rejected one is lost for good.
    # Admitting a wrong paper as core is the opposite error and costs a full
    # read. Landing in the middle class is not an error either way — it is the
    # gate declining to decide on metadata alone, which is what it is for.
    false_rejections = [
        title
        for title, result in zip(positives, positive_results)
        if result.classification is Verdict.REJECTED
    ]
    false_cores = [
        title
        for title, result in zip(negatives, negative_results)
        if result.classification is Verdict.PRELIMINARY_CORE
    ]

    def mean(results: list[Any]) -> float:
        return sum(result.overall_score for result in results) / len(results)

    positive_mean = mean(positive_results)
    negative_mean = mean(negative_results)

    metrics = {
        "false_rejection_rate": round(len(false_rejections) / len(positives), 4),
        "false_core_rate": round(len(false_cores) / len(negatives), 4),
        "core_rate": round(
            sum(
                1
                for result in positive_results
                if result.classification is Verdict.PRELIMINARY_CORE
            )
            / len(positives),
            4,
        ),
        # The two groups carry identical metadata, so any gap between their
        # mean scores comes from the text. A gap at or below zero means the
        # gate cannot tell the labelled sets apart at all, which no threshold
        # on the individual rates would reveal. It is also the metric to read
        # first: ``false_core_rate`` is 0 here mostly because ``core_rate`` is
        # low, so on titles alone a zero there says the gate rarely promotes
        # anything, not that it promotes precisely.
        "score_separation": round(positive_mean - negative_mean, 4),
        "positive_mean_score": round(positive_mean, 4),
        "negative_mean_score": round(negative_mean, 4),
    }

    failures: list[str] = []
    for name, bound in (case.get("metrics") or {}).items():
        if name.endswith("_max"):
            measured = metrics.get(name.removesuffix("_max"))
            if measured is not None and measured > float(bound):
                failures.append(f"{name}: {measured} > {bound}")
        elif name.endswith("_min"):
            measured = metrics.get(name.removesuffix("_min"))
            if measured is not None and measured < float(bound):
                failures.append(f"{name}: {measured} < {bound}")

    notes = [f"wrongly rejected: {title}" for title in false_rejections]
    notes += [f"wrongly called core: {title}" for title in false_cores]

    return CaseResult(
        case_id=case["id"],
        tier="decision",
        passed=not failures,
        duration_ms=round((time.monotonic() - started) * 1000, 1),
        metrics=metrics,
        failures=failures,
        notes=notes,
    )


RUNNERS = {
    "demo": run_demo_case,
    "retrieval": run_retrieval_case,
    "decision": run_decision_case,
}
