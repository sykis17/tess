"""Health endpoint method support (GET + HEAD for uptime monitors)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_health_get_ok() -> None:
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.aclose = AsyncMock()

    with patch("app.api.health.create_async_redis", return_value=redis):
        with patch(
            "app.api.health.collect_host_metrics",
            return_value={"cpu_percent": 12.4, "mem_percent": 58.1},
        ):
            client = TestClient(app)
            res = client.get("/health")

    assert res.status_code == 200
    assert res.json() == {
        "status": "ok",
        "redis": "ok",
        "cpu_percent": 12.4,
        "mem_percent": 58.1,
    }


def test_health_get_without_host_metrics() -> None:
    """Missing psutil / collection failure still returns status + redis."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.aclose = AsyncMock()

    with patch("app.api.health.create_async_redis", return_value=redis):
        with patch("app.api.health.collect_host_metrics", return_value={}):
            client = TestClient(app)
            res = client.get("/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "redis": "ok"}


def test_health_head_ok() -> None:
    """UptimeRobot and similar monitors often use HEAD — must not 405."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.aclose = AsyncMock()

    with patch("app.api.health.create_async_redis", return_value=redis):
        with patch("app.api.health.collect_host_metrics") as metrics:
            client = TestClient(app)
            res = client.head("/health")

    assert res.status_code == 200
    assert res.content in (b"", b"null")  # empty or framework no-body
    metrics.assert_not_called()
