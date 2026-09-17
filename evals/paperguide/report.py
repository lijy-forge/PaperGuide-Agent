"""Aggregate case results into a report and compare against a baseline."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .runner import CaseResult


def to_payload(results: list[CaseResult]) -> dict:
    """Machine-readable result, suitable for storing as a baseline."""

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": all(result.passed for result in results),
        "cases": [asdict(result) for result in results],
    }


def _metric_delta(current: float, previous: float | None) -> str:
    if previous is None:
        return ""
    change = current - previous
    if abs(change) < 1e-9:
        return " (=)"
    return f" ({change:+.4f})"


def to_markdown(results: list[CaseResult], baseline: dict | None = None) -> str:
    """Human-readable report, with metric movement against a baseline."""

    previous: dict[str, dict[str, float]] = {}
    if baseline:
        for case in baseline.get("cases", []):
            previous[case["case_id"]] = case.get("metrics") or {}

    passed = sum(1 for result in results if result.passed and not result.skipped)
    skipped = sum(1 for result in results if result.skipped)
    failed = sum(1 for result in results if not result.passed)

    lines = [
        "# PaperGuide evaluation",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"**{passed} passed · {failed} failed · {skipped} skipped**",
        "",
        "| Case | Tier | Result | Duration |",
        "| --- | --- | --- | ---: |",
    ]
    for result in results:
        verdict = "skipped" if result.skipped else ("pass" if result.passed else "FAIL")
        lines.append(
            f"| `{result.case_id}` | {result.tier} | {verdict} | {result.duration_ms:.0f} ms |"
        )

    measured = [result for result in results if result.metrics]
    if measured:
        lines += ["", "## Metrics", "", "| Case | Metric | Value |", "| --- | --- | ---: |"]
        for result in measured:
            for name, value in sorted(result.metrics.items()):
                delta = _metric_delta(value, (previous.get(result.case_id) or {}).get(name))
                lines.append(f"| `{result.case_id}` | {name} | {value}{delta} |")

    problems = [result for result in results if result.failures or result.skipped]
    if problems:
        lines += ["", "## Details", ""]
        for result in problems:
            lines.append(f"### `{result.case_id}`")
            if result.skipped:
                lines.append(f"- skipped: {result.skipped}")
            lines.extend(f"- {failure}" for failure in result.failures)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write(results: list[CaseResult], out_dir: Path, baseline_path: Path | None = None) -> Path:
    """Write eval-result.json and eval-report.md; return the markdown path."""

    out_dir.mkdir(parents=True, exist_ok=True)
    baseline = None
    if baseline_path and baseline_path.is_file():
        baseline = json.loads(baseline_path.read_text("utf-8"))

    payload = to_payload(results)
    (out_dir / "eval-result.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), "utf-8"
    )
    markdown_path = out_dir / "eval-report.md"
    markdown_path.write_text(to_markdown(results, baseline), "utf-8")
    return markdown_path
