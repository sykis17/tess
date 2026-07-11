from app.core.config import settings
from app.llm.base import BaseLLM, LLMProvider
from app.llm.gemini import GeminiLLM
from app.llm.ollama import OllamaLLM
from app.llm.types import LLMConfig


def create_llm(
    provider: LLMProvider | str | None = None,
    *,
    config: LLMConfig | None = None,
) -> BaseLLM:
    """Create an LLM provider instance by name or from settings."""
    resolved = LLMProvider(provider or settings.default_llm_provider)

    match resolved:
        case LLMProvider.GEMINI:
            return GeminiLLM(config=config)
        case LLMProvider.OLLAMA:
            return OllamaLLM(config=config)
