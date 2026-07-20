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


def test_snapshot_is_healthy() -> None:
    snap = HealthSnapshot(
        provider_id="p1",
        http_ok=True,
        score=80.0,
        healthy=True,
    )
    assert snapshot_is_healthy(snap, 40.0) is True
    assert snapshot_is_healthy(snap, 90.0) is False
