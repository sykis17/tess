"""Health score calculation from probes and provider metrics."""

from __future__ import annotations

from app.ops.models import HealthSnapshot


def compute_health_score(
    *,
    http_ok: bool,
    latency_ms: float | None,
    redis_ok: bool | None = None,
    cpu_percent: float | None = None,
    mem_percent: float | None = None,
    simulated_unhealthy: bool = False,
    chaos_penalty: float = 0.0,
) -> float:
    """Return 0–100 score. Higher is healthier."""
    if simulated_unhealthy:
        return 0.0

    if not http_ok:
        return max(0.0, 10.0 - chaos_penalty)

    score = 70.0

    if latency_ms is not None:
        if latency_ms <= 100:
            score += 20.0
        elif latency_ms <= 500:
            score += 12.0
        elif latency_ms <= 1500:
            score += 5.0
        elif latency_ms <= 3000:
            score -= 5.0
        else:
            score -= 20.0

    if redis_ok is True:
        score += 5.0
    elif redis_ok is False:
        score -= 25.0

    for pct in (cpu_percent, mem_percent):
        if pct is None:
            continue
        if pct >= 95:
            score -= 20.0
        elif pct >= 85:
            score -= 10.0
        elif pct >= 70:
            score -= 5.0

    score -= chaos_penalty
    return max(0.0, min(100.0, score))


def snapshot_is_healthy(snapshot: HealthSnapshot, min_score: float) -> bool:
    return snapshot.healthy and snapshot.score >= min_score
