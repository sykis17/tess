from collections.abc import AsyncIterator
from typing import Any
import asyncio

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.core.config import settings
from app.llm.base import BaseLLM, LLMProvider
from app.llm.types import (
    LLMConfig,
    LLMRequest,
    LLMResponse,
    extract_content,
    to_langchain_messages,
)
from app.llm.usage import extract_usage


# Ollama on small hardware handles one inference at a time; serialize parallel graph
# branches so queued requests do not burn their HTTP timeout waiting for the model.
_ollama_request_lock = asyncio.Lock()


class OllamaLLM(BaseLLM):
    """Async Ollama provider backed by langchain-ollama."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self._base_url = settings.ollama_base_url
        self._model_name = config.model if config else settings.ollama_model
        self._temperature = config.temperature if config else 0.7

        model_kwargs: dict[str, Any] = {
            "base_url": self._base_url,
            "model": self._model_name,
            "temperature": self._temperature,
            "client_kwargs": {"timeout": settings.ollama_request_timeout_seconds},
        }
        if config and config.max_tokens is not None:
            model_kwargs["num_predict"] = config.max_tokens

        self._model = ChatOllama(**model_kwargs)

    @property
    def provider(self) -> LLMProvider:
        return LLMProvider.OLLAMA

    def get_langchain_model(self) -> BaseChatModel:
        return self._model

    async def generate(self, request: LLMRequest) -> LLMResponse:
        # Lazy import: providers are observed by the graph plane, never the reverse.
        from app.graph.observability import llm_call

        lc_messages = to_langchain_messages(request.messages)
        # llm_call spans the lock wait too — for Ollama the duration is queue + inference.
        with llm_call(self.provider.value, self._model_name) as rec:
            async with _ollama_request_lock:
                result = await self._model.ainvoke(lc_messages)
            prompt_tokens, completion_tokens = extract_usage(result)
            rec.set_usage(prompt_tokens, completion_tokens)
        content = extract_content(result.content)

        return LLMResponse(
            content=content,
            provider=self.provider.value,
            model=self._model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw=result.response_metadata if hasattr(result, "response_metadata") else None,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        from app.graph.observability import llm_call

        lc_messages = to_langchain_messages(request.messages)
        # An abandoned generator records at asyncgen finalization: llm_call.__exit__
        # runs on the GeneratorExit from aclose() with outcome=cancelled + last usage.
        with llm_call(self.provider.value, self._model_name, streaming=True) as rec:
            async with _ollama_request_lock:
                async for chunk in self._model.astream(lc_messages):
                    # The final done chunk carries usage with empty content — it is
                    # seen here even though the content filter below never yields it.
                    rec.set_usage(*extract_usage(chunk))
                    if chunk.content:
                        yield extract_content(chunk.content)

    async def ping(self) -> bool:
        """Check whether the Ollama server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url.rstrip('/')}/api/tags")
                return response.is_success
        except httpx.HTTPError:
            return False
