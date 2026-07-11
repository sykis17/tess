from collections.abc import AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.llm.base import BaseLLM, LLMProvider
from app.llm.types import (
    LLMConfig,
    LLMRequest,
    LLMResponse,
    extract_content,
    to_langchain_messages,
)


class GeminiLLM(BaseLLM):
    """Async Gemini provider backed by langchain-google-genai."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required for the Gemini provider. "
                "Set it in your environment or .env file."
            )

        self._model_name = config.model if config else settings.gemini_model
        self._temperature = config.temperature if config else 0.7
        self._max_tokens = config.max_tokens if config else None

        model_kwargs: dict[str, Any] = {
            "model": self._model_name,
            "google_api_key": settings.gemini_api_key,
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            model_kwargs["max_output_tokens"] = self._max_tokens

        self._model = ChatGoogleGenerativeAI(**model_kwargs)

    @property
    def provider(self) -> LLMProvider:
        return LLMProvider.GEMINI

    def get_langchain_model(self) -> BaseChatModel:
        return self._model

    async def generate(self, request: LLMRequest) -> LLMResponse:
        lc_messages = to_langchain_messages(request.messages)
        result = await self._model.ainvoke(lc_messages)
        content = extract_content(result.content)

        return LLMResponse(
            content=content,
            provider=self.provider.value,
            model=self._model_name,
            raw=result.response_metadata if hasattr(result, "response_metadata") else None,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        lc_messages = to_langchain_messages(request.messages)
        async for chunk in self._model.astream(lc_messages):
            if chunk.content:
                yield extract_content(chunk.content)
