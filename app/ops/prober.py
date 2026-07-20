"""HTTP health prober for registered cloud providers."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.ops.models import ChaosKind, CloudProvider, HealthSnapshot, OpsEvent
from app.ops.scoring import compute_health_score
from app.ops.store import OpsStore, get_store, persist_store
from app.providers.cloud import get_adapter

logger = logging.getLogger(__name__)


def _chaos_penalty(provider: CloudProvider) -> float:
    if not provider.chaos.enabled or provider.chaos.kind == ChaosKind.NONE:
        return 0.0
    kind = provider.chaos.kind
    if kind == ChaosKind.MARK_UNHEALTHY:
        return 100.0
    if kind == ChaosKind.HEALTH_5XX:
        return 80.0
    if kind == ChaosKind.HIGH_LATENCY:
        return 25.0
    if kind in (ChaosKind.WORKER_DOWN, ChaosKind.REDIS_PARTITION, ChaosKind.CPU_BURN):
        return 40.0
    return 15.0


async def probe_provider(
    provider: CloudProvider,
    *,
    timeout_seconds: float = 5.0,
    store: OpsStore | None = None,
) -> HealthSnapshot:
    """Probe provider /health and merge provider-native metrics."""
    ops = store or get_store()
    adapter = get_adapter(provider.type)
    provider_metrics: dict[str, Any] = adapter.fetch_metrics(provider)

    if provider.simulate_unhealthy or (
        provider.chaos.enabled and provider.chaos.kind == ChaosKind.MARK_UNHEALTHY
    ):
        snapshot = HealthSnapshot(
            provider_id=provider.id,
            http_ok=False,
            latency_ms=None,
            redis_ok=False,
            provider_metrics=provider_metrics,
            score=0.0,
            last_error="simulated_unhealthy",
            healthy=False,
            simulated=True,
        )
        ops.append_snapshot(snapshot)
        return snapshot

    if provider.chaos.enabled and provider.chaos.kind == ChaosKind.HEALTH_5XX:
        snapshot = HealthSnapshot(
            provider_id=provider.id,
            http_ok=False,
            latency_ms=provider.chaos.latency_ms,
            redis_ok=None,
            provider_metrics=provider_metrics,
            score=compute_health_score(
                http_ok=False,
                latency_ms=provider.chaos.latency_ms,
                chaos_penalty=_chaos_penalty(provider),
            ),
            last_error="chaos_health_5xx",
            healthy=False,
            simulated=True,
        )
        ops.append_snapshot(snapshot)
        return snapshot

    url = f"{provider.base_url}/health"
    http_ok = False
    latency_ms: float | None = None
    redis_ok: bool | None = None
    last_error: str | None = None
    body: dict[str, Any] = {}

    extra_latency = 0.0
    if provider.chaos.enabled and provider.chaos.kind == ChaosKind.HIGH_LATENCY:
        extra_latency = provider.chaos.latency_ms / 1000.0

    start = time.perf_counter()
    try:
        if extra_latency > 0:
            import asyncio

            await asyncio.sleep(min(extra_latency, 3.0))
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(url)
            latency_ms = (time.perf_counter() - start) * 1000.0
            http_ok = response.status_code == 200
            if not http_ok:
                last_error = f"http_{response.status_code}"
            else:
                try:
                    body = response.json()
                    redis_status = body.get("redis")
                    if redis_status is not None:
                        redis_ok = redis_status == "ok"
                except Exception:
                    body = {}
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        last_error = str(exc)
        http_ok = False

    cpu = provider_metrics.get("cpu_utilization")
    mem = provider_metrics.get("mem_percent")
    if isinstance(cpu, (int, float)):
        cpu_percent = float(cpu)
    else:
        cpu_percent = None
    mem_percent = float(mem) if isinstance(mem, (int, float)) else None

    if provider.chaos.enabled and provider.chaos.kind == ChaosKind.REDIS_PARTITION:
        redis_ok = False
        last_error = last_error or "chaos_redis_partition"

    if provider.chaos.enabled and provider.chaos.kind == ChaosKind.CPU_BURN:
        cpu_percent = 99.0

    if provider.chaos.enabled and provider.chaos.kind == ChaosKind.WORKER_DOWN:
        http_ok = False
        last_error = last_error or "chaos_worker_down"

    score = compute_health_score(
        http_ok=http_ok,
        latency_ms=latency_ms,
        redis_ok=redis_ok,
        cpu_percent=cpu_percent,
        mem_percent=mem_percent,
        chaos_penalty=_chaos_penalty(provider),
    )
    healthy = http_ok and score >= 40.0 and redis_ok is not False

    snapshot = HealthSnapshot(
        provider_id=provider.id,
        http_ok=http_ok,
        latency_ms=latency_ms,
        redis_ok=redis_ok,
        cpu_percent=cpu_percent,
        mem_percent=mem_percent,
        provider_metrics={**provider_metrics, "health_body": body},
        score=score,
        last_error=last_error,
        healthy=healthy,
        simulated=provider.chaos.enabled,
    )
    ops.append_snapshot(snapshot)
    return snapshot


async def probe_all_providers(
    *,
    store: OpsStore | None = None,
    timeout_seconds: float = 5.0,
) -> list[HealthSnapshot]:
    ops = store or get_store()
    results: list[HealthSnapshot] = []
    for provider in ops.list_providers():
        if not provider.enabled:
            continue
        try:
            snap = await probe_provider(
                provider, timeout_seconds=timeout_seconds, store=ops
            )
            results.append(snap)
        except Exception:
            logger.exception("probe failed for %s", provider.id)
            ops.append_event(
                OpsEvent(
                    event_type="probe_error",
                    provider_id=provider.id,
                    details={},
                )
            )
    persist_store()
    return results
