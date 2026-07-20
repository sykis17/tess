"""Chaos injection for simulated provider issues."""

from __future__ import annotations

from app.ops.models import ChaosConfig, ChaosKind, OpsEvent
from app.ops.store import OpsStore, get_store, persist_store


def set_chaos(
    provider_id: str,
    kind: ChaosKind,
    *,
    latency_ms: float = 2500.0,
    enabled: bool = True,
    store: OpsStore | None = None,
) -> ChaosConfig:
    ops = store or get_store()
    provider = ops.get_provider(provider_id)
    if provider is None:
        raise ValueError(f"unknown provider: {provider_id}")

    chaos = ChaosConfig(kind=kind, latency_ms=latency_ms, enabled=enabled)
    if kind == ChaosKind.NONE:
        chaos = ChaosConfig(kind=ChaosKind.NONE, enabled=False)
        provider.simulate_unhealthy = False
    elif kind == ChaosKind.MARK_UNHEALTHY:
        provider.simulate_unhealthy = True
    else:
        provider.simulate_unhealthy = False

    provider.chaos = chaos
    ops.upsert_provider(provider)
    ops.append_event(
        OpsEvent(
            event_type=f"chaos_{kind.value}",
            provider_id=provider_id,
            details={"latency_ms": latency_ms, "enabled": enabled},
        )
    )
    persist_store()
    return chaos


def clear_chaos(provider_id: str, *, store: OpsStore | None = None) -> None:
    set_chaos(provider_id, ChaosKind.NONE, enabled=False, store=store)
