"""Structured-output adapter over GPT Researcher's unified LLM function."""

import asyncio
import inspect
import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from paperpilot.analysis.exceptions import (
    AnalysisLLMInvocationError,
    AnalysisLLMResponseError,
    AnalysisSchemaValidationError,
)
from paperpilot.analysis.llm_protocol import StructuredModelT


class GPTResearcherStructuredLLM:
    """Validate JSON generated through GPT Researcher's provider-neutral LLM API.

    Construct this with an existing GPT Researcher Config. The adapter reads its
    smart model/provider settings but never mutates it. Tests may inject a completion
    callable; production usage lazily imports ``create_chat_completion``.

    Minimal production assembly::

        config = Config()
        llm = GPTResearcherStructuredLLM(config)
        reader = PaperReader(llm, PaperContextBuilder(), EvidenceMapper())
        result = reader.analyze(document)

    API credentials remain in GPT Researcher's normal configuration environment.
    """

    _JSON_FENCE_RE = re.compile(
        r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL
    )

    def __init__(
        self,
        config: Any,
        *,
        completion_callable: Callable[..., Any] | None = None,
    ):
        self.model_name = str(config.smart_llm_model)
        self.llm_provider = str(config.smart_llm_provider)
        self.max_tokens = int(config.smart_token_limit)
        self.llm_kwargs = dict(getattr(config, "llm_kwargs", {}) or {})
        self.request_timeout_seconds = float(
            self.llm_kwargs.get("request_timeout", 180.0)
        )
        self._completion_callable = completion_callable

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModelT],
    ) -> StructuredModelT:
        """Invoke GPT Researcher once and strictly validate its JSON response."""

        schema = json.dumps(
            response_model.model_json_schema(), ensure_ascii=False, sort_keys=True
        )
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\nReturn only one JSON object conforming "
                    "exactly to the supplied schema."
                ),
            },
            {
                "role": "user",
                "content": f"{user_prompt}\n\nJSON Schema:\n{schema}",
            },
        ]

        try:
            completion = self._completion_callable or self._load_completion_callable()
            provider_options: dict[str, Any] = {}
            request_max_tokens = self.max_tokens
            if self.llm_provider.casefold() == "deepseek":
                provider_options["response_format"] = {"type": "json_object"}
                request_max_tokens = min(request_max_tokens, 8_192)
            raw_response = completion(
                messages=messages,
                model=self.model_name,
                temperature=0.0,
                max_tokens=request_max_tokens,
                llm_provider=self.llm_provider,
                stream=False,
                llm_kwargs=dict(self.llm_kwargs),
                **provider_options,
            )
            if inspect.isawaitable(raw_response):
                raw_response = self._run_awaitable(
                    raw_response, timeout_seconds=self.request_timeout_seconds
                )
        except AnalysisLLMInvocationError:
            raise
        except Exception as error:
            raise AnalysisLLMInvocationError(
                f"GPT Researcher LLM invocation failed: {type(error).__name__}"
            ) from error

        payload = self._parse_json_response(raw_response)
        try:
            return response_model.model_validate(payload)
        except ValidationError as error:
            raise AnalysisSchemaValidationError(
                "LLM JSON response does not satisfy the requested schema"
            ) from error

    @staticmethod
    def _load_completion_callable() -> Callable[..., Any]:
        from gpt_researcher.utils.llm import create_chat_completion

        return create_chat_completion

    @staticmethod
    def _run_awaitable(awaitable: Any, *, timeout_seconds: float) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(asyncio.wait_for(awaitable, timeout=timeout_seconds))
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise AnalysisLLMInvocationError(
            "synchronous structured LLM adapter cannot run inside an active event loop"
        )

    @classmethod
    def _parse_json_response(cls, raw_response: Any) -> Any:
        if not isinstance(raw_response, str) or not raw_response.strip():
            raise AnalysisLLMResponseError("LLM response must be non-empty JSON text")

        text = raw_response.strip()
        fence = cls._JSON_FENCE_RE.search(text)
        candidate = fence.group(1).strip() if fence else text
        try:
            if fence:
                return json.loads(candidate)
            start = candidate.find("{")
            if start < 0:
                raise json.JSONDecodeError("no JSON object", candidate, 0)
            value, end = json.JSONDecoder().raw_decode(candidate[start:])
            if candidate[start + end :].strip():
                raise json.JSONDecodeError(
                    "unexpected content after JSON object", candidate, start + end
                )
            return value
        except json.JSONDecodeError as error:
            raise AnalysisLLMResponseError(
                "LLM response does not contain one valid JSON object"
            ) from error
