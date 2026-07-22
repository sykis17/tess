"""Unit tests for ops health scoring."""

from app.ops.scoring import compute_health_score, snapshot_is_healthy
from app.ops.models import HealthSnapshot


def test_score_healthy_fast() -> None:
    score = compute_health_score(http_ok=True, latency_ms=50.0, redis_ok=True)
    assert score >= 90.0


def test_score_simulated_unhealthy_is_zero() -> None:
    assert (
        compute_health_score(
            http_ok=True, latency_ms=10.0, simulated_unhealthy=True
        )
        == 0.0
    )


def test_score_http_fail() -> None:
    score = compute_health_score(http_ok=False, latency_ms=None)
    assert score <= 10.0


def test_score_high_cpu_penalty() -> None:
    base = compute_health_score(http_ok=True, latency_ms=50.0, redis_ok=True)
    high = compute_health_score(
        http_ok=True, latency_ms=50.0, redis_ok=True, cpu_percent=96.0
    )
    assert high == base - 20.0


def test_score_high_mem_penalty() -> None:
    base = compute_health_score(http_ok=True, latency_ms=50.0, redis_ok=True)
    mid = compute_health_score(
        http_ok=True, latency_ms=50.0, redis_ok=True, mem_percent=72.0
    )
    assert mid == base - 5.0


def test_snapshot_is_healthy() -> None:
    snap = HealthSnapshot(
        provider_id="p1",
        http_ok=True,
        score=80.0,
        healthy=True,
    )
    assert snapshot_is_healthy(snap, 40.0) is True
    assert snapshot_is_healthy(snap, 90.0) is False
