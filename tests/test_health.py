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
        client = TestClient(app)
        res = client.head("/health")

    assert res.status_code == 200
    assert res.content in (b"", b"null")  # empty or framework no-body
