"""Provider-neutral protocol for synchronous structured LLM generation."""

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


@runtime_checkable
class StructuredLLMProtocol(Protocol):
    """Structural interface used by PaperReader for validated LLM output."""

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModelT],
    ) -> StructuredModelT:
        """Generate and validate one structured response."""
        ...
