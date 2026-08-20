"""Command-line entry point for explicitly requested real smoke runs."""

import argparse
import sys
from pathlib import Path

from paperpilot.domain import PaperSource
from paperpilot.export import ExportFormat

from .config import SmokeTestConfig
from .runner import SmokeTestRunner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one real PaperPilot smoke test")
    parser.add_argument("--question", default=SmokeTestConfig().question)
    parser.add_argument("--max-papers", type=int, default=1)
    parser.add_argument(
        "--format",
        choices=[item.value for item in ExportFormat],
        default="markdown",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("runtime-data/smoke"),
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=[PaperSource.ARXIV.value, PaperSource.SEMANTIC_SCHOLAR.value],
        dest="sources",
        help="Repeat to enable multiple sources; defaults to arxiv",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = SmokeTestConfig(
        question=args.question,
        max_papers=args.max_papers,
        export_format=ExportFormat(args.format),
        timeout_seconds=args.timeout,
        output_directory=args.output_directory,
        sources=[PaperSource(item) for item in (args.sources or ["arxiv"])],
    )
    result = SmokeTestRunner().run(config)
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    return 0 if result.status.value == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
