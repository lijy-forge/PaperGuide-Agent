"""Intent planner implementations."""

from paperguide.analysis import StructuredLLMProtocol

from .models import ResearchIntent
from .prompts import INTENT_SYSTEM_PROMPT


class StructuredLLMResearchIntentPlanner:
    """Generate a ResearchIntent through an injected structured LLM."""

    def __init__(self, llm: StructuredLLMProtocol):
        self._llm = llm

    def plan(self, question: str) -> ResearchIntent:
        normalized = question.strip()
        if not normalized:
            raise ValueError("research question must not be empty")
        result = self._llm.generate_structured(
            system_prompt=INTENT_SYSTEM_PROMPT,
            user_prompt=normalized,
            response_model=ResearchIntent,
        )
        return result if isinstance(result, ResearchIntent) else ResearchIntent.model_validate(result)


class DeterministicResearchIntentPlanner:
    """Offline planner used by Demo Mode without an LLM or network."""

    def plan(self, question: str) -> ResearchIntent:
        normalized = question.strip()
        if not normalized:
            raise ValueError("research question must not be empty")
        return ResearchIntent(research_question=normalized, required_concepts=[normalized])
