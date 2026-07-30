from app.core.config import settings
from app.core.posture import EgressRefusedError, is_internal_base_url
from app.llm.base import BaseLLM, LLMProvider
from app.llm.gemini import GeminiLLM
from app.llm.ollama import OllamaLLM
from app.llm.types import LLMConfig


def _ensure_provider_allowed_under_strict(resolved: LLMProvider) -> None:
    """Sovereign-strict refuses third-party LLM egress before construction."""
    if resolved is LLMProvider.GEMINI:
        raise EgressRefusedError(
            "sovereign-strict posture refuses the Gemini provider (third-party "
            "egress); use Ollama or set TESS_RUNTIME_POSTURE=availability-first."
        )
    if resolved is LLMProvider.OLLAMA and not is_internal_base_url(
        settings.ollama_base_url
    ):
        raise EgressRefusedError(
            "sovereign-strict posture refuses non-internal OLLAMA_BASE_URL "
            f"{settings.ollama_base_url!r}; expected a loopback/private address, "
            "a docker service name, or host.docker.internal."
        )


def create_llm(
    provider: LLMProvider | str | None = None,
    *,
    config: LLMConfig | None = None,
) -> BaseLLM:
    """Create an LLM provider instance by name or from settings."""
    resolved = LLMProvider(provider or settings.default_llm_provider)

    if settings.posture_is_strict():
        _ensure_provider_allowed_under_strict(resolved)

    match resolved:
        case LLMProvider.GEMINI:
            return GeminiLLM(config=config)
        case LLMProvider.OLLAMA:
            return OllamaLLM(config=config)
