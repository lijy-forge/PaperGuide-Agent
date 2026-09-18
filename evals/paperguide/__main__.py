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
# Baselines live in the repository, not under --out. They are the reference a
# later run is compared against, so they must survive the output directory
# being overwritten and must travel with the code rather than sitting in one
# machine's gitignored scratch space.
BASELINES_DIR = Path(__file__).parent / "baselines"


def _baseline_path(tier: str | None, override: str | None) -> Path | None:
    if override:
        return Path(override)
    return BASELINES_DIR / f"{tier}.json" if tier else None


def storable(results: list[CaseResult]) -> bool:
    """Whether a run is fit to become a baseline.

    A skipped case measured nothing, so storing the run would make the next
    comparison read a source outage as a change in quality.
    """

    return bool(results) and not any(result.skipped for result in results)


def _store_baseline(tier: str, result_file: Path) -> None:
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    target = BASELINES_DIR / f"{tier}.json"
    target.write_text(result_file.read_text("utf-8"), "utf-8")
    print(f"baseline updated: {target}")


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
    parser.add_argument(
        "--out",
        default="runtime-data/evaluation",
        help="where this run's report goes; overwritten each time and gitignored",
    )
    parser.add_argument(
        "--baseline",
        help=f"eval-result.json to compare against (default: {BASELINES_DIR}/<tier>.json)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="store this run as the tier's committed baseline",
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

    baseline = _baseline_path(arguments.tier, arguments.baseline)
    markdown = report.write(results, Path(arguments.out), baseline)
    print(f"\nreport: {markdown}")
    if baseline and not baseline.is_file():
        print(f"no baseline yet at {baseline}; --update-baseline records one")

    if arguments.update_baseline:
        if not arguments.tier:
            print("--update-baseline needs --tier", file=sys.stderr)
            return 2
        if not storable(results):
            print("not stored: some cases were skipped", file=sys.stderr)
            return 1
        _store_baseline(arguments.tier, Path(arguments.out) / "eval-result.json")

    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
