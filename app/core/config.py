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
    ollama_request_timeout_seconds: float = 300.0

    default_llm_provider: str = "gemini"

    tavily_api_key: str | None = None
    search_max_urls: int = 3
    search_fetch_timeout_seconds: float = 15.0
    search_cache_ttl_seconds: int = 3600

    stream_throttle_ms: int = 75
    progress_heartbeat_seconds: float = 10.0

    pipeline_soft_time_limit_seconds: int = 900
    pipeline_hard_time_limit_seconds: int = 910

    skip_llm_follow_ups: bool = False

    # Multi-cloud ops control plane
    ops_local_base_url: str = "http://127.0.0.1:8000"
    # Public WS for chat clients (ops-ui). When unset, derived from ops_local_base_url.
    # Set on Hetzner CP to the public host (e.g. wss://tess.example or ws://5.78.x.x)
    # so ops-ui does not advertise loopback mid-demo.
    ops_public_ws_base_url: str | None = None
    ops_hetzner_region: str = "fsn1"
    ops_aws_base_url: str | None = None
    ops_aws_region: str = "us-east-1"
    ops_aws_credentials_ref: str | None = "AWS_ROLE_ARN"
    ops_gcp_base_url: str | None = None
    ops_gcp_region: str = "us-central1"
    ops_gcp_credentials_ref: str | None = "GCP_SERVICE_ACCOUNT_JSON"
    ops_preferred_provider_id: str | None = None
    ops_admin_token: str | None = None
    # JSON object {"operator_id": "token", ...}; preferred over ops_admin_token
    ops_admin_tokens: str | None = None
    ops_probe_interval_seconds: float = 30.0
    ops_failover_failure_threshold: int = 3
    ops_failover_recovery_threshold: int = 2
    ops_latency_threshold_ms: float = 5000.0
    ops_probe_enabled: bool = True
    ops_persist_enabled: bool = True


settings = Settings()


def should_skip_llm_follow_ups() -> bool:
    """Return True when presenter should skip the follow-up LLM call."""
    if settings.skip_llm_follow_ups:
        return True
    return ":1b" in settings.ollama_model
