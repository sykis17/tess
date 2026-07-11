from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import Enum

from langchain_core.language_models.chat_models import BaseChatModel

from app.llm.types import LLMRequest, LLMResponse


class LLMProvider(str, Enum):
    GEMINI = "gemini"
    OLLAMA = "ollama"


class BaseLLM(ABC):
    """Unified async interface for TESS LLM providers."""

    @property
    @abstractmethod
    def provider(self) -> LLMProvider:
        """Return the provider identifier for this LLM instance."""

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a complete response for the given request."""

    @abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream response content token-by-token for the given request."""

    @abstractmethod
    def get_langchain_model(self) -> BaseChatModel:
        """Return the underlying LangChain model for Phase 3 LangGraph nodes."""
