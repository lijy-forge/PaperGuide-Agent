"""Shared structural contracts for PaperPilot retriever adapters."""

from typing import Protocol, runtime_checkable

from paperpilot.domain import PaperCandidate


@runtime_checkable
class RetrieverProtocol(Protocol):
    """Structural interface implemented by paper metadata retrievers."""

    def search(
        self, query: str, max_results: int = 10
    ) -> list[PaperCandidate]:
        """Search a data source and return normalized paper candidates."""

        ...
