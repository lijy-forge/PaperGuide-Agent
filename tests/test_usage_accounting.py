"""Token and cost accounting for LLM calls."""

import pytest
from paperguide.usage import MeteredStructuredLLM, ModelPrice, UsageLedger
from pydantic import BaseModel


class Reply(BaseModel):
    text: str


class OtherReply(BaseModel):
    text: str


class _Fake:
    def __init__(self, text: str = "an answer") -> None:
        self.text = text
        self.calls = 0

    def generate_structured(self, *, system_prompt, user_prompt, response_model):
        self.calls += 1
        return response_model(text=self.text)


class _Failing:
    def generate_structured(self, *, system_prompt, user_prompt, response_model):
        raise RuntimeError("provider down")


def make(model: str = "gpt-4o-mini") -> tuple[MeteredStructuredLLM, UsageLedger, _Fake]:
    ledger = UsageLedger(model)
    inner = _Fake()
    return MeteredStructuredLLM(inner, ledger), ledger, inner


def test_a_call_is_attributed_to_its_response_model():
    """The response model is what distinguishes reading from verifying from
    writing, so it is the label worth grouping by."""

    llm, ledger, _ = make()

    llm.generate_structured(system_prompt="s", user_prompt="u", response_model=Reply)
    llm.generate_structured(system_prompt="s", user_prompt="u", response_model=OtherReply)
    llm.generate_structured(system_prompt="s", user_prompt="u", response_model=Reply)

    summary = ledger.summary()
    assert summary.calls == 3
    assert summary.by_label["Reply"].calls == 2
    assert summary.by_label["OtherReply"].calls == 1


def test_the_wrapper_returns_what_the_inner_model_produced():
    llm, _, inner = make()

    result = llm.generate_structured(system_prompt="s", user_prompt="u", response_model=Reply)

    assert result.text == inner.text
    assert inner.calls == 1


def test_a_failed_call_is_not_billed():
    """A provider error consumed no completion, so charging for it would
    overstate the cost of a run that mostly failed."""

    ledger = UsageLedger("gpt-4o-mini")
    llm = MeteredStructuredLLM(_Failing(), ledger)

    with pytest.raises(RuntimeError):
        llm.generate_structured(system_prompt="s", user_prompt="u", response_model=Reply)

    assert ledger.summary().calls == 0


def test_a_longer_prompt_costs_more():
    llm, ledger, _ = make()

    llm.generate_structured(system_prompt="s", user_prompt="short", response_model=Reply)
    small = ledger.summary().input_tokens
    llm.generate_structured(system_prompt="s", user_prompt="a much longer prompt " * 50, response_model=Reply)

    assert ledger.summary().input_tokens > small * 2


def test_an_unpriced_model_reports_unknown_cost_not_zero():
    """A missing price must not read as a free run."""

    ledger = UsageLedger("some-unlisted-model")
    llm = MeteredStructuredLLM(_Fake(), ledger)
    llm.generate_structured(system_prompt="s", user_prompt="u", response_model=Reply)

    summary = ledger.summary()
    assert summary.total_tokens > 0
    assert summary.cost_usd is None


def test_cost_follows_the_configured_price():
    ledger = UsageLedger("m", prices={"m": ModelPrice(1_000_000.0, 1_000_000.0)})
    ledger.record("x", input_tokens=2, output_tokens=3)

    # One dollar per token at this price, so the total is the token count.
    assert ledger.summary().cost_usd == pytest.approx(5.0)


def test_the_heaviest_call_site_is_identified():
    ledger = UsageLedger("gpt-4o-mini")
    ledger.record("cheap", input_tokens=10, output_tokens=1)
    ledger.record("expensive", input_tokens=900, output_tokens=100)

    label, usage = ledger.summary().most_expensive()
    assert label == "expensive"
    assert usage.total_tokens == 1000


def test_an_empty_run_has_no_heaviest_call_site():
    assert UsageLedger("gpt-4o-mini").summary().most_expensive() is None
