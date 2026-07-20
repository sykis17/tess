"""Combined health logs (own probes + provider-native metrics)."""

from __future__ import annotations

from typing import Any

from app.ops.store import OpsStore, get_store


def combined_health_logs(
    *,
    provider_id: str | None = None,
    limit: int = 100,
    store: OpsStore | None = None,
) -> list[dict[str, Any]]:
    """
    Merge local HealthSnapshot fields with provider_metrics for a single timeline.
    """
    ops = store or get_store()
    snaps = ops.list_snapshots(provider_id=provider_id, limit=limit)
    logs: list[dict[str, Any]] = []
    for snap in snaps:
        provider = ops.get_provider(snap.provider_id)
        logs.append(
            {
                "id": snap.id,
                "provider_id": snap.provider_id,
                "provider_type": provider.type.value if provider else None,
                "provider_name": provider.name if provider else None,
                "checked_at": snap.checked_at.isoformat(),
                "own": {
                    "http_ok": snap.http_ok,
                    "latency_ms": snap.latency_ms,
                    "redis_ok": snap.redis_ok,
                    "cpu_percent": snap.cpu_percent,
                    "mem_percent": snap.mem_percent,
                    "disk_percent": snap.disk_percent,
                    "score": snap.score,
                    "healthy": snap.healthy,
                    "last_error": snap.last_error,
                    "simulated": snap.simulated,
                },
                "provider_native": snap.provider_metrics,
            }
        )
    return logs
