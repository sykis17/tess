from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str = "redis://redis:6379/0"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_request_timeout_seconds: float = 120.0

    default_llm_provider: str = "gemini"

    tavily_api_key: str | None = None
    search_max_urls: int = 3
    search_fetch_timeout_seconds: float = 15.0
    search_cache_ttl_seconds: int = 3600


settings = Settings()
