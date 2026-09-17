"""Run the PaperGuide evaluation cases.

    python -m evals.paperguide --tier demo
    python -m evals.paperguide --tier retrieval --out runtime-data/evaluation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import report
from .runner import RUNNERS, CaseResult

CASES_DIR = Path(__file__).parent / "cases"


def load_cases(tier: str | None) -> list[dict]:
    """Load case files, optionally limited to one tier."""

    cases = []
    for path in sorted(CASES_DIR.rglob("*.yaml")):
        case = yaml.safe_load(path.read_text("utf-8"))
        case.setdefault("tier", path.parent.name)
        if tier is None or case["tier"] == tier:
            cases.append(case)
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.paperguide")
    parser.add_argument(
        "--tier",
        choices=sorted(RUNNERS),
        help="only run cases of this tier; retrieval reaches the network",
    )
    parser.add_argument("--out", default="runtime-data/evaluation")
    parser.add_argument(
        "--baseline",
        help="eval-result.json to compare metrics against",
    )
    arguments = parser.parse_args(argv)

    cases = load_cases(arguments.tier)
    if not cases:
        print("no cases matched", file=sys.stderr)
        return 2

    results: list[CaseResult] = []
    for case in cases:
        results.append(RUNNERS[case["tier"]](case))
        last = results[-1]
        mark = "skip" if last.skipped else ("ok" if last.passed else "FAIL")
        print(f"  {mark:4} {last.case_id}")

    out_dir = Path(arguments.out)
    baseline = Path(arguments.baseline) if arguments.baseline else None
    markdown = report.write(results, out_dir, baseline)
    print(f"\nreport: {markdown}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
