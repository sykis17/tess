from pydantic import field_validator
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

    @field_validator("ops_public_ws_base_url", mode="before")
    @classmethod
    def _empty_public_ws_base_url_is_unset(cls, value: object) -> object:
        # OPS_PUBLIC_WS_BASE_URL= (empty, as .env.example ships) must mean
        # "unset", never "clear the advertised WS URL" (P0.2 Defect C).
        if isinstance(value, str) and not value.strip():
            return None
        return value
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

    # Control-plane HA (etcd lease + Redis CAS fencing). Empty endpoints = HA off.
    ops_ha_enabled: bool = False
    ops_etcd_endpoints: str = ""
    ops_cp_instance_id: str = "cp-default"
    ops_etcd_lease_ttl_seconds: int = 10
    ops_etcd_campaign_interval_seconds: float = 2.0
    # Which backend is authoritative for durable CP writes. "etcd" is the linearizable
    # cutover default (fence term + durable blob in one store, dissolving the external-bump
    # "unelectable" limitation); "redis" keeps the historical single-store behavior. Only
    # consulted when HA is active — HA-off always uses the unconditional Redis single-writer
    # path.
    ops_fence_authority: str = "etcd"

    # Observability (self-hosted, opt-in, OFF by default). See deploy/MULTI_CLOUD.md.
    # Metrics = Prometheus pull; traces = OTLP/HTTP → self-hosted collector. No SaaS.
    ops_metrics_enabled: bool = False
    ops_metrics_worker_port: int = 9109
    ops_tracing_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_traces_sampler_ratio: float = 1.0
    otel_service_name: str = "tess-ops"

    # Product-graph observability (W2) — flags separate from ops_* by design, so
    # enabling one plane never silently starts paying the other's instrumentation
    # cost. Shares the OTLP endpoint + worker :9109 exposition above.
    graph_metrics_enabled: bool = False
    graph_tracing_enabled: bool = False
    graph_otel_service_name: str = "tess-graph"

    # W3 graph checkpointing (recoverable-loss run scratch; doctrine in
    # deploy/MULTI_CLOUD.md). OFF by default: the compiled_graph singleton the
    # zero-infra eval harness imports stays bare; the RedisCheckpointSaver is
    # constructed lazily at first flag-on use, never at import. TTL sized from
    # the Step 0 measurement: one L4 run = 19 checkpoints, ~839 KB total, so an
    # hour-long resume window (~4x the 910 s hard limit) stays MB-scale.
    graph_checkpointing_enabled: bool = False
    graph_checkpoint_ttl_seconds: int = 3600

    def ops_ha_active(self) -> bool:
        """True when CP HA election/fencing is enabled and etcd is configured."""
        if not self.ops_ha_enabled:
            return False
        return bool(self.ops_etcd_endpoints.strip())

    def ops_tracing_active(self) -> bool:
        """True when tracing is enabled and an OTLP endpoint is configured."""
        return self.ops_tracing_enabled and bool(self.otel_exporter_otlp_endpoint)

    def graph_tracing_active(self) -> bool:
        """True when graph tracing is enabled and an OTLP endpoint is configured."""
        return self.graph_tracing_enabled and bool(self.otel_exporter_otlp_endpoint)


settings = Settings()


def should_skip_llm_follow_ups() -> bool:
    """Return True when presenter should skip the follow-up LLM call.

    SKIP_LLM_FOLLOW_UPS=true forces skip on any model. Models whose name
    contains ``:1b`` always skip (hard floor); false cannot re-enable LLM chips.
    """
    if settings.skip_llm_follow_ups:
        return True
    return ":1b" in settings.ollama_model
