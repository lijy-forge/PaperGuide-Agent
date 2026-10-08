"""Unit tests for constructing the Anthropic chat provider.

The provider is built with a dummy key and inspected; no network calls are
made. The point of interest is `request_timeout`, which the bootstrap passes
for every provider but which ChatAnthropic does not accept under that name.
"""
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gpt_researcher.llm_provider.generic.base import (
    GenericLLMProvider,
    content_to_text,
)
from gpt_researcher.utils.llm import create_chat_completion


class TestAnthropicProvider(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "test-key"

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = self._orig

    def test_request_timeout_becomes_the_clients_own_timeout(self):
        """The OpenAI spelling must not survive into the Anthropic call.

        Left as `request_timeout`, pydantic files it under model_kwargs and
        langchain forwards it to messages.create(), which raises TypeError on
        every call — the whole run fails before a single token is spent.
        """
        provider = GenericLLMProvider.from_provider(
            "anthropic",
            model="claude-sonnet-5",
            request_timeout=180.0,
            verbose=False,
        )

        self.assertEqual(provider.llm.default_request_timeout, 180.0)
        self.assertNotIn("request_timeout", provider.llm.model_kwargs)

    def test_timeout_is_left_alone_when_already_correct(self):
        provider = GenericLLMProvider.from_provider(
            "anthropic", model="claude-sonnet-5", timeout=42.0, verbose=False
        )

        self.assertEqual(provider.llm.default_request_timeout, 42.0)


class TestContentToText(unittest.TestCase):
    """A thinking model answers in blocks; the pipeline needs the text."""

    def test_plain_string_is_unchanged(self):
        self.assertEqual(content_to_text("hello"), "hello")

    def test_thinking_block_is_dropped_and_text_kept(self):
        blocks = [
            {"type": "thinking", "thinking": "", "signature": "abc"},
            {"type": "text", "text": '{"variants":[]}'},
        ]

        self.assertEqual(content_to_text(blocks), '{"variants":[]}')

    def test_several_text_blocks_are_joined(self):
        blocks = [
            {"type": "text", "text": '{"var'},
            {"type": "text", "text": 'iants":[]}'},
        ]

        self.assertEqual(content_to_text(blocks), '{"variants":[]}')

    def test_empty_content_becomes_empty_string(self):
        self.assertEqual(content_to_text(None), "")
        self.assertEqual(content_to_text([]), "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-fable-5",
        "claude-fable-5-1",
        "claude-opus-4-8",
    ],
)
async def test_temperature_is_withheld_from_models_that_deprecated_it(model):
    """Each of these answers a 400 when `temperature` is sent.

    Verified against the live API on 2026-09-19. One such call fails the run,
    so the model must reach the provider with no temperature of its own.
    """
    provider = MagicMock()
    provider.get_chat_response = AsyncMock(return_value="ok")

    with patch(
        "gpt_researcher.utils.llm.get_llm", return_value=provider
    ) as mock_get_llm:
        await create_chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            model=model,
            temperature=0.4,
            llm_provider="anthropic",
        )

    assert mock_get_llm.call_args.kwargs["temperature"] is None


if __name__ == "__main__":
    unittest.main()
