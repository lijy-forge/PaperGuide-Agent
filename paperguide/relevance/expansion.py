"""Query expansion implementations with deterministic safety bounds."""

from paperguide.analysis import StructuredLLMProtocol

from .models import QueryExpansionOutput, QueryVariant, ResearchIntent
from .prompts import QUERY_EXPANSION_SYSTEM_PROMPT


class LLMQueryExpansionService:
    """Expand an intent using an injected structured LLM."""

    def __init__(self, llm: StructuredLLMProtocol):
        self._llm = llm

    def expand(self, intent: ResearchIntent) -> list[QueryVariant]:
        result = self._llm.generate_structured(
            system_prompt=QUERY_EXPANSION_SYSTEM_PROMPT,
            user_prompt=intent.model_dump_json(),
            response_model=QueryExpansionOutput,
        )
        output = result if isinstance(result, QueryExpansionOutput) else QueryExpansionOutput.model_validate(result)
        return list(output.variants)


class DeterministicQueryExpansionService:
    """Offline query expansion that preserves the supplied intent only."""

    def expand(self, intent: ResearchIntent) -> list[QueryVariant]:
        base = " ".join(intent.required_concepts)
        relations = list(intent.relation_requirements)
        return [QueryVariant(query=base, purpose="direct required concept query", covered_concepts=list(intent.required_concepts), covered_relations=relations)]
