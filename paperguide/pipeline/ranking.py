"""Rank retrieved candidates by BM25 against the research question.

Neither adapter reports a relevance score, so candidates used to reach the
caller in whatever order the sources happened to return them, concatenated.
Scoring them locally means a partial match still counts and still ranks,
instead of the retrieval being all-or-nothing.

BM25 is lexical: it cannot connect a Chinese question to an English paper.
Bridging that gap needs query translation or embeddings and is deliberately
not attempted here.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from paperguide.domain import PaperCandidate

_TOKEN_RE = re.compile(r"[a-z0-9]+|[一-鿿]")
_STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it", "of", "on", "or", "that", "the", "to", "with", "using", "via", "this", "these", "those", "we", "our", "their", "its", "been", "was", "were", "will", "can", "may", "study", "research", "paper", "approach", "method", "based"]
)
_K1 = 1.5
_B = 0.75
_TITLE_WEIGHT = 3


def tokenize(text: str) -> list[str]:
    """Split into lowercase word tokens, with CJK kept per character."""

    return _TOKEN_RE.findall(text.casefold())


def content_terms(text: str) -> list[str]:
    """Tokens worth matching on, with stopwords removed."""

    return [token for token in tokenize(text) if token not in _STOPWORDS]


def _document_terms(paper: PaperCandidate) -> list[str]:
    """Terms for one candidate, counting the title more than the abstract."""

    title = content_terms(paper.title or "")
    abstract = content_terms(paper.abstract or "")
    return title * _TITLE_WEIGHT + abstract


def score_candidates(papers: list[PaperCandidate], question: str) -> list[float]:
    """Return a BM25 score per candidate, aligned with ``papers``."""

    query_terms = content_terms(question)
    documents = [_document_terms(paper) for paper in papers]
    if not query_terms or not documents:
        return [0.0] * len(papers)

    lengths = [len(document) for document in documents]
    average_length = sum(lengths) / len(lengths) or 1.0
    containing: Counter[str] = Counter()
    for document in documents:
        containing.update(set(document))
    total = len(documents)

    scores: list[float] = []
    for index, document in enumerate(documents):
        counts = Counter(document)
        score = 0.0
        for term in query_terms:
            occurrences = counts.get(term)
            if not occurrences:
                continue
            documents_with_term = containing[term]
            idf = math.log(
                1 + (total - documents_with_term + 0.5) / (documents_with_term + 0.5)
            )
            denominator = occurrences + _K1 * (
                1 - _B + _B * lengths[index] / average_length
            )
            score += idf * occurrences * (_K1 + 1) / (denominator or 1.0)
        scores.append(score)
    return scores


def rank_by_question(papers: list[PaperCandidate], question: str) -> list[PaperCandidate]:
    """Order candidates by BM25, breaking ties deterministically."""

    scores = score_candidates(papers, question)
    ordered = sorted(
        zip(scores, papers, strict=True),
        key=lambda pair: (
            -pair[0],
            -(pair[1].publication_year or 0),
            pair[1].normalized_title.casefold(),
        ),
    )
    return [paper for _, paper in ordered]
