"""Unit tests for GPT Researcher's provider-neutral structured LLM adapter."""

import asyncio
import inspect
import json
import unittest
from types import SimpleNamespace

from paperguide.analysis import (
    AnalysisLLMInvocationError,
    AnalysisLLMResponseError,
    AnalysisSchemaValidationError,
    StructuredLLMProtocol,
)
from paperguide.integrations import GPTResearcherStructuredLLM
from pydantic import BaseModel, ConfigDict


class SmallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


def make_config():
    return SimpleNamespace(
        smart_llm_model="fake-model",
        smart_llm_provider="fake-provider",
        smart_token_limit=512,
        llm_kwargs={"endpoint": "configured"},
    )


class TestGPTResearcherStructuredLLM(unittest.TestCase):
    def test_awaitable_respects_adapter_timeout(self):
        config = make_config()
        config.llm_kwargs = {"request_timeout": 0.01}

        async def never_returns(**kwargs):
            await asyncio.sleep(10)
            return '{"answer":"late"}'

        adapter = GPTResearcherStructuredLLM(config, completion_callable=never_returns)

        with self.assertRaises(AnalysisLLMInvocationError):
            adapter.generate_structured(
                system_prompt="system", user_prompt="user", response_model=SmallResponse
            )

    def test_adapter_satisfies_structured_protocol(self):
        adapter = GPTResearcherStructuredLLM(
            make_config(), completion_callable=lambda **kwargs: '{"answer":"ok"}'
        )

        self.assertIsInstance(adapter, StructuredLLMProtocol)

    def test_valid_json_is_validated_as_model(self):
        adapter = GPTResearcherStructuredLLM(
            make_config(), completion_callable=lambda **kwargs: '{"answer":"ok"}'
        )

        result = adapter.generate_structured(
            system_prompt="system", user_prompt="user", response_model=SmallResponse
        )

        self.assertEqual(result, SmallResponse(answer="ok"))

    def test_markdown_json_fence_is_parsed(self):
        adapter = GPTResearcherStructuredLLM(
            make_config(),
            completion_callable=lambda **kwargs: '```json\n{"answer":"ok"}\n```',
        )

        result = adapter.generate_structured(
            system_prompt="system", user_prompt="user", response_model=SmallResponse
        )

        self.assertEqual(result.answer, "ok")

    def test_explanatory_prefix_before_json_is_bounded_and_parsed(self):
        adapter = GPTResearcherStructuredLLM(
            make_config(),
            completion_callable=lambda **kwargs: 'Structured result:\n{"answer":"ok"}',
        )

        result = adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=SmallResponse,
        )

        self.assertEqual(result.answer, "ok")

    def test_async_gpt_researcher_completion_is_bridged(self):
        async def completion(**kwargs):
            return '{"answer":"async"}'

        adapter = GPTResearcherStructuredLLM(
            make_config(), completion_callable=completion
        )

        result = adapter.generate_structured(
            system_prompt="system", user_prompt="user", response_model=SmallResponse
        )

        self.assertEqual(result.answer, "async")

    def test_invalid_json_raises_response_error(self):
        adapter = GPTResearcherStructuredLLM(
            make_config(), completion_callable=lambda **kwargs: "not json"
        )

        with self.assertRaises(AnalysisLLMResponseError):
            adapter.generate_structured(
                system_prompt="system", user_prompt="user", response_model=SmallResponse
            )

    def test_schema_mismatch_raises_validation_error(self):
        adapter = GPTResearcherStructuredLLM(
            make_config(), completion_callable=lambda **kwargs: '{"wrong":"field"}'
        )

        with self.assertRaises(AnalysisSchemaValidationError):
            adapter.generate_structured(
                system_prompt="system", user_prompt="user", response_model=SmallResponse
            )

    def test_underlying_exception_is_wrapped(self):
        def fail(**kwargs):
            raise ConnectionError("provider unavailable")

        adapter = GPTResearcherStructuredLLM(make_config(), completion_callable=fail)

        with self.assertRaises(AnalysisLLMInvocationError) as context:
            adapter.generate_structured(
                system_prompt="system", user_prompt="user", response_model=SmallResponse
            )
        self.assertNotIn("provider unavailable", str(context.exception))

    def test_trailing_non_json_content_is_rejected(self):
        adapter = GPTResearcherStructuredLLM(
            make_config(),
            completion_callable=lambda **kwargs: '{"answer":"ok"} trailing',
        )

        with self.assertRaises(AnalysisLLMResponseError):
            adapter.generate_structured(
                system_prompt="system", user_prompt="user", response_model=SmallResponse
            )

    def test_adapter_does_not_use_eval(self):
        source = inspect.getsource(GPTResearcherStructuredLLM._parse_json_response)

        self.assertNotIn("eval(", source)
        self.assertIn("json.JSONDecoder", source)

    def test_call_inputs_and_config_are_not_modified(self):
        config = make_config()
        original_kwargs = dict(config.llm_kwargs)
        captured = {}

        def completion(**kwargs):
            captured.update(kwargs)
            return json.dumps({"answer": "ok"})

        adapter = GPTResearcherStructuredLLM(config, completion_callable=completion)
        system_prompt = "system prompt"
        user_prompt = "user prompt"

        adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=SmallResponse,
        )

        self.assertEqual(config.llm_kwargs, original_kwargs)
        self.assertEqual(system_prompt, "system prompt")
        self.assertEqual(user_prompt, "user prompt")
        self.assertEqual(captured["model"], "fake-model")
        self.assertIn("JSON Schema", captured["messages"][1]["content"])

    def test_deepseek_requests_provider_json_output(self):
        config = make_config()
        config.smart_llm_provider = "deepseek"
        captured = {}

        def completion(**kwargs):
            captured.update(kwargs)
            return '{"answer":"ok"}'

        adapter = GPTResearcherStructuredLLM(
            config,
            completion_callable=completion,
        )
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=SmallResponse,
        )

        self.assertEqual(
            captured["response_format"],
            {"type": "json_object"},
        )
        self.assertEqual(captured["max_tokens"], 512)

    def test_other_providers_do_not_receive_deepseek_json_option(self):
        captured = {}

        def completion(**kwargs):
            captured.update(kwargs)
            return '{"answer":"ok"}'

        adapter = GPTResearcherStructuredLLM(
            make_config(),
            completion_callable=completion,
        )
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=SmallResponse,
        )

        self.assertNotIn("response_format", captured)

    def test_deepseek_structured_output_budget_is_bounded(self):
        config = make_config()
        config.smart_llm_provider = "deepseek"
        config.smart_token_limit = 12_000
        captured = {}

        def completion(**kwargs):
            captured.update(kwargs)
            return '{"answer":"ok"}'

        GPTResearcherStructuredLLM(
            config,
            completion_callable=completion,
        ).generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=SmallResponse,
        )

        self.assertEqual(captured["max_tokens"], 8_192)


if __name__ == "__main__":
    unittest.main()
