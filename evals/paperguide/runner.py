"""Case runners for the two evaluation tiers.

``demo`` runs the whole pipeline against the synthetic corpus. It needs no
credentials and no network, and it is deterministic, so it can gate every
change. It cannot say anything about retrieval quality: the fake retriever
returns the corpus itself, so recall is 1 by construction.

``retrieval`` calls the real arXiv and Semantic Scholar adapters and stops
there. It is the tier that can measure recall. It deliberately plans with the
deterministic planner rather than the LLM one, so a recall number reflects the
retrievers rather than today's sampling from a model. arXiv needs no key;
SEMANTIC_SCHOLAR_API_KEY only raises the rate limit.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paperguide.domain import PaperSource, ResearchConfig

from .checks import INVARIANTS, METRICS


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
    skipped: str | None = None


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
    config = ResearchConfig(
        question=case["question"],
        max_papers=limit,
        sources=[PaperSource.ARXIV, PaperSource.SEMANTIC_SCHOLAR],
    )
    search = PaperSearchPipeline(_default_retrievers())
    result = search.search(config)

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
    }

    failures = [f"missed: {item}" for item in misses] if misses else []
    for name, minimum in (case.get("metrics") or {}).items():
        measured = metrics.get(name.removesuffix("_min"))
        if measured is not None and measured < float(minimum):
            failures.append(f"{name}: {measured} < {minimum}")

    return CaseResult(
        case_id=case["id"],
        tier="retrieval",
        passed=not failures,
        duration_ms=round((time.monotonic() - started) * 1000, 1),
        metrics=metrics,
        failures=failures,
    )


RUNNERS = {"demo": run_demo_case, "retrieval": run_retrieval_case}
