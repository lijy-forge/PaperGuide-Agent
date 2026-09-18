"""Estimated token and cost accounting for structured LLM calls.

The numbers here are **estimates**. The upstream completion helper returns the
response text and nothing else, so a provider's reported usage never reaches
this process; tokens are counted locally with the model's own encoding.
Against OpenAI models that lands within a few percent, which is enough to
answer the questions worth asking — which stage dominates a run, and whether
a change made it cheaper — but it is not a billing record.

Cost is only computed for models with a price on file. An unpriced model
still accumulates tokens, and its cost is reported as unknown rather than as
zero, so a missing price cannot masquerade as a free run.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field

from paperguide.analysis import StructuredLLMProtocol
from paperguide.analysis.llm_protocol import StructuredModelT

_FALLBACK_ENCODING = "cl100k_base"


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens, as published by the provider."""

    input_per_million: float
    output_per_million: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_million
            + output_tokens * self.output_per_million
        ) / 1_000_000


# Prices change, so this is a starting point to be overridden per deployment
# rather than a maintained price list.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "gpt-4o": ModelPrice(2.50, 10.00),
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "gpt-4.1": ModelPrice(2.00, 8.00),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60),
}


@dataclass
class CallUsage:
    """What one labelled call site consumed across a run."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class UsageSummary:
    """A run's estimated consumption, by call site and in total."""

    model: str
    by_label: dict[str, CallUsage] = field(default_factory=dict)
    cost_usd: float | None = None

    @property
    def calls(self) -> int:
        return sum(item.calls for item in self.by_label.values())

    @property
    def input_tokens(self) -> int:
        return sum(item.input_tokens for item in self.by_label.values())

    @property
    def output_tokens(self) -> int:
        return sum(item.output_tokens for item in self.by_label.values())

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def most_expensive(self) -> tuple[str, CallUsage] | None:
        """The call site consuming the most tokens, which is what to optimise."""

        if not self.by_label:
            return None
        return max(self.by_label.items(), key=lambda item: item[1].total_tokens)


class TokenCounter:
    """Count tokens with the model's encoding, falling back when unknown."""

    def __init__(self, model: str) -> None:
        self._encoding = self._resolve(model)

    @staticmethod
    def _resolve(model: str):
        import tiktoken

        try:
            return tiktoken.encoding_for_model(model)
        except Exception:  # noqa: BLE001 - an unknown model is expected, not exceptional
            return tiktoken.get_encoding(_FALLBACK_ENCODING)

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text or ""))


class UsageLedger:
    """Accumulate estimated usage across a run.

    Calls arrive from bounded-concurrency workers, so recording is locked.
    """

    def __init__(self, model: str, prices: dict[str, ModelPrice] | None = None) -> None:
        self.model = model
        self._prices = DEFAULT_PRICES if prices is None else prices
        self._counter = TokenCounter(model)
        self._by_label: dict[str, CallUsage] = defaultdict(CallUsage)
        self._lock = threading.Lock()

    def record_text(self, label: str, prompt: str, completion: str) -> None:
        """Record one call by counting the text it sent and received."""

        self.record(
            label,
            input_tokens=self._counter.count(prompt),
            output_tokens=self._counter.count(completion),
        )

    def record(self, label: str, *, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            usage = self._by_label[label]
            usage.calls += 1
            usage.input_tokens += max(0, input_tokens)
            usage.output_tokens += max(0, output_tokens)

    def summary(self) -> UsageSummary:
        with self._lock:
            by_label = {
                label: CallUsage(usage.calls, usage.input_tokens, usage.output_tokens)
                for label, usage in self._by_label.items()
            }
        price = self._prices.get(self.model)
        summary = UsageSummary(model=self.model, by_label=by_label)
        if price is not None:
            summary.cost_usd = round(
                price.cost(summary.input_tokens, summary.output_tokens), 6
            )
        return summary


class MeteredStructuredLLM:
    """Wrap any structured LLM and record what each call consumed.

    The label defaults to the response model's name, which is what
    distinguishes the call sites: reading a paper, verifying evidence and
    writing a synthesis stage each request a different model.
    """

    def __init__(self, inner: StructuredLLMProtocol, ledger: UsageLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModelT],
    ) -> StructuredModelT:
        result = self._inner.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
        )
        # Measured after the call so a failed one is not billed; the response
        # text is unavailable here, so the validated object stands in for it.
        self._ledger.record_text(
            response_model.__name__,
            system_prompt + user_prompt,
            result.model_dump_json() if hasattr(result, "model_dump_json") else str(result),
        )
        return result
