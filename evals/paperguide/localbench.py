"""Compare ranking strategies over a local PDF corpus, without any network.

Retrieval quality has two separable parts: whether the sources return the
paper at all, and whether the matching logic ranks it. The first needs API
access; the second does not. This benchmark isolates the second by ranking a
folder of PDFs the user already has, so a change to the matching logic can be
measured while the APIs are unreachable or rate limited.

The numbers here are not recall against arXiv. They answer a narrower
question: given a corpus that definitely contains the right papers, does the
matching logic rank them near the top?

    python -m evals.paperguide.localbench --corpus corpus.json --truth case.yaml
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import yaml

TOKEN_RE = re.compile(r"[a-z0-9]+|[一-鿿]")
STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it", "of", "on", "or", "that", "the", "to", "with", "using", "via", "this", "these", "those", "we", "our", "their", "its", "been", "was", "were", "will", "can", "may"]
)
TITLE_MATCH_THRESHOLD = 0.70


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.casefold())


def content_tokens(text: str) -> list[str]:
    return [token for token in tokenize(text) if token not in STOPWORDS]


def rank_conjunctive(query: str, corpus: list[dict]) -> list[int]:
    """Mimic the current adapter: every query token is required.

    ``_build_url`` joins every token of the query with AND, stopwords
    included, so a document has to contain all of them. Nothing is scored:
    a document either qualifies or it does not.
    """

    required = tokenize(query)
    hits = []
    for index, document in enumerate(corpus):
        haystack = set(tokenize(document["title"] + " " + document["text"]))
        if all(token in haystack for token in required):
            hits.append(index)
    return hits


def rank_bm25(query: str, corpus: list[dict], k1: float = 1.5, b: float = 0.75) -> list[int]:
    """Rank by BM25 over content words, so a partial match still counts."""

    documents = [content_tokens(item["title"] + " " + item["title"] + " " + item["text"]) for item in corpus]
    lengths = [len(document) for document in documents]
    average = sum(lengths) / len(lengths) if lengths else 0.0
    frequency: Counter[str] = Counter()
    for document in documents:
        frequency.update(set(document))
    total = len(documents)

    scores = []
    query_tokens = content_tokens(query)
    for index, document in enumerate(documents):
        counts = Counter(document)
        score = 0.0
        for token in query_tokens:
            if token not in counts:
                continue
            appearances = frequency[token]
            idf = math.log(1 + (total - appearances + 0.5) / (appearances + 0.5))
            term = counts[token]
            denominator = term + k1 * (1 - b + b * lengths[index] / (average or 1))
            score += idf * term * (k1 + 1) / (denominator or 1)
        scores.append((score, index))
    scores.sort(key=lambda pair: (-pair[0], pair[1]))
    return [index for score, index in scores if score > 0]


STRATEGIES = {"conjunctive": rank_conjunctive, "bm25": rank_bm25}


def _matches_truth(title: str, truth: list[str]) -> bool:
    lowered = title.casefold()
    for wanted in truth:
        target = wanted.casefold()
        if target in lowered or lowered in target:
            return True
        if SequenceMatcher(None, lowered, target).ratio() >= TITLE_MATCH_THRESHOLD:
            return True
    return False


def evaluate(corpus: list[dict], query: str, truth: list[str], cutoff: int) -> dict:
    """Recall and first-hit rank for each strategy."""

    relevant = {index for index, item in enumerate(corpus) if _matches_truth(item["title"], truth)}
    report = {"corpus": len(corpus), "labelled_present": len(relevant), "strategies": {}}
    for name, strategy in STRATEGIES.items():
        ranking = strategy(query, corpus)
        top = ranking[:cutoff]
        found = [index for index in top if index in relevant]
        first = next((position + 1 for position, index in enumerate(ranking) if index in relevant), None)
        report["strategies"][name] = {
            "returned": len(ranking),
            f"recall_at_{cutoff}": round(len(found) / len(relevant), 4) if relevant else 0.0,
            "first_relevant_rank": first,
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.paperguide.localbench")
    parser.add_argument("--corpus", type=Path, required=True, help="JSON list of {title, text}")
    parser.add_argument("--truth", type=Path, required=True, help="case file with ground_truth_titles")
    parser.add_argument("--cutoff", type=int, default=20)
    arguments = parser.parse_args(argv)

    corpus = json.loads(arguments.corpus.read_text("utf-8"))
    case = yaml.safe_load(arguments.truth.read_text("utf-8"))
    truth = case.get("ground_truth_titles") or []
    if not truth:
        print("the case has no ground_truth_titles")
        return 1

    report = evaluate(corpus, case["question"], truth, arguments.cutoff)
    print(f"query           : {case['question']}")
    print(f"corpus          : {report['corpus']} documents")
    print(f"labelled present: {report['labelled_present']}/{len(truth)} of the labelled papers are in it")
    print()
    for name, numbers in report["strategies"].items():
        print(f"  {name:12} returned={numbers['returned']:4}  "
              f"recall@{arguments.cutoff}={numbers[f'recall_at_{arguments.cutoff}']:.2f}  "
              f"first_hit_rank={numbers['first_relevant_rank']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
