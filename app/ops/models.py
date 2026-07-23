"""Pydantic models for the multi-cloud ops control plane."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class ProviderType(str, Enum):
    HETZNER = "hetzner"
    AWS = "aws"
    GCP = "gcp"
    CUSTOMER = "customer"


class RoutingPolicy(str, Enum):
    """How new sessions are assigned across healthy providers."""

    ACTIVE_ONLY = "active_only"  # failover: all new traffic to active provider
    SHARE = "share"  # round-robin / hash across healthy
    BALANCE = "balance"  # weight by health/performance score
    DUAL = "dual"  # two concurrent sticky homes: active + next-best
    PERFORMANCE = "performance"  # single active; score-chase with anti-flap


class ChaosKind(str, Enum):
    NONE = "none"
    HIGH_LATENCY = "high_latency"
    HEALTH_5XX = "health_5xx"
    MARK_UNHEALTHY = "mark_unhealthy"
    WORKER_DOWN = "worker_down"
    REDIS_PARTITION = "redis_partition"
    CPU_BURN = "cpu_burn"


class ChaosConfig(BaseModel):
    kind: ChaosKind = ChaosKind.NONE
    latency_ms: float = 2500.0
    enabled: bool = False


class CloudProvider(BaseModel):
    id: str
    type: ProviderType
    name: str
    base_url: str
    region: str | None = None
    enabled: bool = True
    credentials_ref: str | None = None
    org_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    simulate_unhealthy: bool = False
    chaos: ChaosConfig = Field(default_factory=ChaosConfig)
    ws_base_url: str | None = None
    # Optional override for Performance auto-wake bar (beats global margin).
    # Use a higher value for costlier standbys (e.g. AWS) so they need a clearer win.
    auto_wake_score_margin: float | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    def effective_ws_base_url(self) -> str:
        if self.ws_base_url:
            return self.ws_base_url.rstrip("/")
        http = self.base_url
        if http.startswith("https://"):
            return "wss://" + http[len("https://") :]
        if http.startswith("http://"):
            return "ws://" + http[len("http://") :]
        return http


class ProviderCreate(BaseModel):
    type: ProviderType
    name: str
    base_url: str
    region: str | None = None
    enabled: bool = True
    credentials_ref: str | None = None
    org_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    ws_base_url: str | None = None


class ProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    region: str | None = None
    enabled: bool | None = None
    credentials_ref: str | None = None
    tags: list[str] | None = None
    ws_base_url: str | None = None
    simulate_unhealthy: bool | None = None


class HealthSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("snap"))
    provider_id: str
    checked_at: datetime = Field(default_factory=utc_now)
    http_ok: bool = False
    latency_ms: float | None = None
    redis_ok: bool | None = None
    cpu_percent: float | None = None
    mem_percent: float | None = None
    disk_percent: float | None = None
    provider_metrics: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    last_error: str | None = None
    healthy: bool = False
    simulated: bool = False


class OpsEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    event_type: str
    ts: datetime = Field(default_factory=utc_now)
    provider_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RoutingPolicySettings(BaseModel):
    policy: RoutingPolicy = RoutingPolicy.ACTIVE_ONLY
    preferred_provider_id: str | None = None
    auto_failover: bool = True
    failure_threshold: int = 3
    recovery_threshold: int = 2
    latency_p95_threshold_ms: float = 5000.0
    min_score_for_healthy: float = 40.0
    # Performance anti-flap
    performance_score_margin: float = 10.0
    performance_streak_required: int = 2
    # When True + PERFORMANCE: may enqueue wake for offline AWS/GCP standbys.
    # Default False = online-only (no cloud start from the control plane).
    auto_wake: bool = False
    # Refuse auto-wake if latest snapshot is older than this (seconds).
    # Stopped boxes cannot be re-probed; stale history must not wake blind.
    auto_wake_max_score_age_s: float = 3600.0
    # After a failed wake, do not retry that provider until cooldown elapses.
    auto_wake_failure_cooldown_s: float = 600.0


class RoutingState(BaseModel):
    active_provider_id: str | None = None
    # Dual mode: second concurrent chat home (XOR with PERFORMANCE policy)
    dual_peer_id: str | None = None
    consecutive_failures: dict[str, int] = Field(default_factory=dict)
    consecutive_successes: dict[str, int] = Field(default_factory=dict)
    last_failover_at: datetime | None = None
    last_failover_from: str | None = None
    last_failover_to: str | None = None
    sessions_dropped_last: int = 0
    # Performance challenger streak (anti-flap)
    performance_challenger_id: str | None = None
    performance_challenger_streak: int = 0
    # Auto-wake: at most one standby wake in flight (lock only — not an auto-sleep timer)
    auto_wake_inflight_provider_id: str | None = None
    auto_wake_inflight_at: datetime | None = None
    auto_wake_inflight_task_id: str | None = None
    # provider_id -> ISO cooldown-until after failed wake (anti-stampede)
    auto_wake_cooldown_until: dict[str, datetime] = Field(default_factory=dict)
    # Last decision trail line for ops-ui (also mirrored in /ops/events)
    auto_wake_last_decision: str | None = None
    auto_wake_last_decision_at: datetime | None = None


class SessionAssignment(BaseModel):
    session_id: str
    provider_id: str
    assigned_at: datetime = Field(default_factory=utc_now)
    policy: RoutingPolicy


class ComparisonRunRequest(BaseModel):
    name: str = "default"
    provider_ids: list[str] = Field(default_factory=list)
    inject_chaos: dict[str, ChaosKind] = Field(default_factory=dict)


class ComparisonReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cmp"))
    name: str
    created_at: datetime = Field(default_factory=utc_now)
    provider_scores: dict[str, float] = Field(default_factory=dict)
    failover_ms: float | None = None
    session_success_rate: float | None = None
    notes: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class ByoRegisterRequest(BaseModel):
    name: str
    base_url: str
    org_id: str
    region: str | None = None
    ws_base_url: str | None = None
    api_key: str | None = None


class ActiveRoutingResponse(BaseModel):
    active_provider_id: str | None
    policy: RoutingPolicy
    base_url: str | None = None
    ws_base_url: str | None = None
    provider_changed: bool = False
    message: str | None = None
    dual_peer_id: str | None = None
    dual_homes: list[str] = Field(default_factory=list)


class ProviderChangedMessage(BaseModel):
    """WebSocket / client envelope when failover drops in-flight sessions."""

    type: str = "provider_changed"
    from_provider_id: str | None = None
    to_provider_id: str | None = None
    sessions_dropped: int = 0
    message: str = (
        "Provider changed — in-flight answer was interrupted. "
        "Reconnect and resubmit if needed."
    )
    ws_base_url: str | None = None


class SeamlessMigrationStatus(BaseModel):
    """Phase 3+ placeholder: seamless mid-session migration is not in failover v1."""

    available: bool = False
    reason: str = (
        "Seamless mid-session migration requires shared Redis / control-plane "
        "session state. Failover v1 drops in-flight sessions and signals reconnect."
    )
