"""Provider-neutral contracts for intent and query planning."""

from typing import Protocol, runtime_checkable

from .models import QueryVariant, ResearchIntent


@runtime_checkable
class ResearchIntentPlannerProtocol(Protocol):
    def plan(self, question: str) -> ResearchIntent:
        """Extract a validated research intent."""
        ...


@runtime_checkable
class QueryExpansionProtocol(Protocol):
    def expand(self, intent: ResearchIntent) -> list[QueryVariant]:
        """Create short, academic-search query variants."""
        ...
