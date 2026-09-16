"""Offline RetrieverProtocol implementation backed by demo seed data."""

from copy import deepcopy

from paperguide.domain import PaperCandidate, PaperSource

from .seed import DemoSeed, create_demo_seed


class FakeRetriever:
    """Return deterministic synthetic papers without issuing network requests."""

    source = PaperSource.ARXIV

    def __init__(self, seed: DemoSeed | None = None) -> None:
        self._seed = seed or create_demo_seed()

    def search(self, query: str, max_results: int = 10) -> list[PaperCandidate]:
        """Return at most ``max_results`` isolated candidates for any query."""

        if not query.strip():
            return []
        return deepcopy(list(self._seed.papers[:max_results]))
