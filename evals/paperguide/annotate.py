"""Helpers for building and checking a retrieval ground-truth set.

Labelling by hand means writing down identifiers, and a wrong identifier is
worse than no label: the system retrieves the right paper, the label does not
match it, and recall looks permanently low with nothing to point at. So a case
is written with paper *titles*, and ``resolve`` turns them into identifiers by
asking the real APIs. Nothing is typed from memory.

    # 1. see what the current retriever returns, to label from
    python -m evals.paperguide.annotate pool "视觉SLAM回环检测" --limit 20

    # 2. turn the titles in a case file into verified identifiers
    python -m evals.paperguide.annotate resolve evals/paperguide/cases/retrieval/xxx.yaml

    # 3. check identifiers already in a case still resolve
    python -m evals.paperguide.annotate verify evals/paperguide/cases/retrieval/xxx.yaml
"""

from __future__ import annotations

import argparse
import sys
from difflib import SequenceMatcher
from pathlib import Path

import yaml

TITLE_MATCH_THRESHOLD = 0.72


def _retrievers():
    from paperguide.bootstrap.factory import _default_retrievers

    return _default_retrievers()


def _identifier(paper) -> str | None:
    """Prefer arXiv, then DOI, then Semantic Scholar."""

    if getattr(paper, "arxiv_id", None):
        return f"arxiv:{str(paper.arxiv_id).removeprefix('arXiv:').removeprefix('arxiv:')}"
    if getattr(paper, "doi", None):
        return f"doi:{paper.doi}"
    if getattr(paper, "semantic_scholar_id", None):
        return f"s2:{paper.semantic_scholar_id}"
    return None


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.casefold().strip(), right.casefold().strip()).ratio()


def pool(query: str, limit: int) -> int:
    """Print what the current retrievers return, as a labelling starting point.

    These are candidates, not ground truth. Labelling only from this list
    measures precision, never recall — a paper the retriever never returns can
    never be marked missing. Add the papers you know should be there too.
    """

    from paperguide.domain import PaperSource, ResearchConfig
    from paperguide.pipeline import PaperSearchPipeline

    config = ResearchConfig(
        question=query,
        max_papers=limit,
        sources=[PaperSource.ARXIV, PaperSource.SEMANTIC_SCHOLAR],
    )
    result = PaperSearchPipeline(_retrievers()).search(config)
    if result.source_errors:
        print(f"source errors: {result.source_errors}", file=sys.stderr)
    if not result.papers:
        print("no candidates returned", file=sys.stderr)
        return 1

    print(f"# {len(result.papers)} candidates for {query!r}")
    print("# paste the relevant ones under ground_truth, and add what is missing")
    print("ground_truth:")
    for paper in result.papers:
        identifier = _identifier(paper) or "UNRESOLVED"
        print(f'  - "{identifier}"   # {paper.publication_year or "????"} {paper.title[:70]}')
    return 0


STOPWORDS = frozenset(
    "a an and are as at be by for from in into is of on or the to towards with"
    " using via über".split()
)


def _distinctive_terms(title: str, keep: int = 5) -> str:
    """Return the most distinctive words of a title.

    The arXiv adapter ANDs every token of a query, stopwords included, so a
    full title asks for a paper containing all ten of its words and usually
    finds nothing. Searching on a few content words instead is far more likely
    to surface the paper, and the title similarity check below is what decides
    whether the result is actually the right one.
    """

    words = [word for word in title.replace(":", " ").split() if word.casefold() not in STOPWORDS]
    words.sort(key=len, reverse=True)
    return " ".join(words[:keep])


def _lookup(title: str, retrievers) -> tuple[str | None, str, float]:
    """Return (identifier, matched title, similarity) for the best match."""

    best: tuple[str | None, str, float] = (None, "", 0.0)
    queries = [title, _distinctive_terms(title)]
    for query in dict.fromkeys(queries):
        for retriever in retrievers:
            try:
                candidates = retriever.search(query, 5)
            except Exception as error:  # noqa: BLE001 - report and try the next source
                print(f"    source failed: {type(error).__name__}: {error}", file=sys.stderr)
                continue
            for paper in candidates:
                score = _similarity(title, paper.title)
                if score > best[2]:
                    best = (_identifier(paper), paper.title, score)
        if best[2] >= TITLE_MATCH_THRESHOLD:
            break
    return best


def resolve(path: Path, apply: bool) -> int:
    """Turn ``ground_truth_titles`` into verified identifiers."""

    case = yaml.safe_load(path.read_text("utf-8"))
    titles = case.get("ground_truth_titles") or []
    if not titles:
        print("no ground_truth_titles in this case", file=sys.stderr)
        return 1

    retrievers = _retrievers()
    resolved: list[str] = []
    unresolved: list[str] = []
    for title in titles:
        identifier, matched, score = _lookup(str(title), retrievers)
        if identifier and score >= TITLE_MATCH_THRESHOLD:
            print(f"  ok   {identifier:34} {score:.2f}  {matched[:58]}")
            resolved.append(identifier)
        else:
            print(f"  MISS {'-':34} {score:.2f}  best was: {matched[:58] or '(nothing)'}")
            unresolved.append(str(title))

    print(f"\nresolved {len(resolved)}/{len(titles)}")
    if unresolved:
        print("unresolved titles stay in the file; check spelling or label them by hand:")
        for title in unresolved:
            print(f"  - {title}")

    if apply and resolved:
        case["ground_truth"] = sorted(set(case.get("ground_truth") or []) | set(resolved))
        path.write_text(yaml.safe_dump(case, allow_unicode=True, sort_keys=False), "utf-8")
        print(f"\nwrote {len(case['ground_truth'])} identifiers into {path}")
    elif resolved:
        print("\nre-run with --apply to write these into the case file")
    return 0


def verify(path: Path) -> int:
    """Check every identifier in ``ground_truth`` still resolves to a paper."""

    case = yaml.safe_load(path.read_text("utf-8"))
    truth = case.get("ground_truth") or []
    if not truth:
        print("ground_truth is empty", file=sys.stderr)
        return 1

    retrievers = _retrievers()
    bad = 0
    for identifier in truth:
        scheme, _, value = str(identifier).partition(":")
        found = ""
        for retriever in retrievers:
            try:
                for paper in retriever.search(value, 3):
                    if _identifier(paper) == identifier:
                        found = paper.title
                        break
            except Exception:  # noqa: BLE001 - a dead source is reported below
                continue
            if found:
                break
        if found:
            print(f"  ok   {identifier:34} {found[:60]}")
        else:
            bad += 1
            print(f"  BAD  {identifier:34} did not resolve to a paper")
    print(f"\n{len(truth) - bad}/{len(truth)} identifiers resolve")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.paperguide.annotate")
    sub = parser.add_subparsers(dest="command", required=True)

    pool_parser = sub.add_parser("pool", help="list what the retrievers return now")
    pool_parser.add_argument("query")
    pool_parser.add_argument("--limit", type=int, default=20)

    resolve_parser = sub.add_parser("resolve", help="titles -> verified identifiers")
    resolve_parser.add_argument("case", type=Path)
    resolve_parser.add_argument("--apply", action="store_true", help="write them into the case")

    verify_parser = sub.add_parser("verify", help="check existing identifiers resolve")
    verify_parser.add_argument("case", type=Path)

    arguments = parser.parse_args(argv)
    if arguments.command == "pool":
        return pool(arguments.query, arguments.limit)
    if arguments.command == "resolve":
        return resolve(arguments.case, arguments.apply)
    return verify(arguments.case)


if __name__ == "__main__":
    raise SystemExit(main())
