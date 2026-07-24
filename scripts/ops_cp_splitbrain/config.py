"""Central harness config — timeouts derived from lease TTL, not magic numbers."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class HarnessConfig:
    cp_a: str
    cp_b: str
    admin_token: str
    lease_ttl_seconds: int
    convergence_timeout: float
    poll_interval: float
    compose_files: tuple[str, ...]
    project_name: str
    redis_service: str
    etcd_service: str
    web_service: str
    standby_service: str
    redis_only_network: str
    second_provider_name: str
    second_provider_base_url: str
    # Observability (s10 only; requires the opt-in docker-compose.ops-obs.yml overlay).
    worker_service: str
    worker_metrics_url: str
    collector_service: str
    spans_file: str

    @property
    def compose_args(self) -> list[str]:
        args: list[str] = []
        for path in self.compose_files:
            args.extend(["-f", path])
        if self.project_name:
            args.extend(["-p", self.project_name])
        return args


def load_config() -> HarnessConfig:
    ttl = max(5, int(os.environ.get("OPS_ETCD_LEASE_TTL_SECONDS", "10")))
    # Plan: CONVERGENCE_TIMEOUT = 3 × lease_TTL (WSL2 jitter included).
    convergence = float(os.environ.get("OPS_HA_CONVERGENCE_TIMEOUT", str(3 * ttl)))
    # ops-obs.yml is opt-in (default empty) so the existing 2-file stack is unchanged;
    # the s10 verification sets OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml.
    compose_files = tuple(
        f
        for f in (
            os.environ.get("OPS_HA_COMPOSE_BASE", "docker-compose.yml"),
            os.environ.get("OPS_HA_COMPOSE_OVERLAY", "docker-compose.ops-ha.yml"),
            os.environ.get("OPS_HA_COMPOSE_OBS", ""),
        )
        if f
    )
    return HarnessConfig(
        cp_a=os.environ.get("OPS_HA_SMOKE_A", "http://127.0.0.1:8000"),
        cp_b=os.environ.get("OPS_HA_SMOKE_B", "http://127.0.0.1:8001"),
        admin_token=os.environ.get("OPS_ADMIN_TOKEN", "ha-harness-token"),
        lease_ttl_seconds=ttl,
        convergence_timeout=convergence,
        poll_interval=float(os.environ.get("OPS_HA_POLL_INTERVAL", "1.0")),
        compose_files=compose_files,
        project_name=os.environ.get("OPS_HA_COMPOSE_PROJECT", "tess-engine"),
        redis_service=os.environ.get("OPS_HA_REDIS_SERVICE", "redis"),
        etcd_service=os.environ.get("OPS_HA_ETCD_SERVICE", "etcd"),
        web_service=os.environ.get("OPS_HA_WEB_SERVICE", "web"),
        standby_service=os.environ.get("OPS_HA_STANDBY_SERVICE", "web-standby"),
        redis_only_network=os.environ.get("OPS_HA_REDIS_NETWORK", "ops-ha-redis"),
        second_provider_name="ha-harness-secondary",
        second_provider_base_url="http://127.0.0.1:18099",
        worker_service=os.environ.get("OPS_HA_WORKER_SERVICE", "worker"),
        worker_metrics_url=os.environ.get("OPS_HA_WORKER_METRICS", "http://127.0.0.1:9109"),
        collector_service=os.environ.get("OPS_HA_COLLECTOR_SERVICE", "otel-collector"),
        spans_file=os.environ.get("OPS_HA_SPANS_FILE", "/spans/spans.json"),
    )
