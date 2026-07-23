"""Prober unit tests with mocked HTTP."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.ops.models import ChaosKind, CloudProvider, ProviderType
from app.ops.prober import probe_provider
from app.ops.chaos import set_chaos
from app.ops.store import OpsStore


def test_probe_simulated_unhealthy() -> None:
    store = OpsStore()
    provider = CloudProvider(
        id="p1",
        type=ProviderType.HETZNER,
        name="P",
        base_url="http://p.example",
        simulate_unhealthy=True,
    )
    store.upsert_provider(provider)
    snap = asyncio.run(probe_provider(provider, store=store))
    assert snap.healthy is False
    assert snap.simulated is True
    assert snap.score == 0.0


def test_probe_http_ok() -> None:
    store = OpsStore()
    provider = CloudProvider(
        id="p2",
        type=ProviderType.GCP,
        name="G",
        base_url="http://g.example",
    )
    store.upsert_provider(provider)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok", "redis": "ok"}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.ops.prober.httpx.AsyncClient", return_value=mock_client):
        snap = asyncio.run(probe_provider(provider, store=store))

    assert snap.http_ok is True
    assert snap.redis_ok is True
    assert snap.healthy is True
    assert snap.score > 40


def test_probe_reads_cpu_mem_from_health_body() -> None:
    store = OpsStore()
    provider = CloudProvider(
        id="p_cpu",
        type=ProviderType.GCP,
        name="G",
        base_url="http://g.example",
    )
    store.upsert_provider(provider)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "redis": "ok",
        "cpu_percent": 96.0,
        "mem_percent": 50.0,
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.ops.prober.httpx.AsyncClient", return_value=mock_client):
        snap = asyncio.run(probe_provider(provider, store=store))

    assert snap.cpu_percent == 96.0
    assert snap.mem_percent == 50.0
    # Base ~95 with redis, minus 20 for cpu>=95 → still healthy at default threshold
    assert snap.score < 90.0
    assert snap.healthy is True


def test_probe_chaos_5xx() -> None:
    store = OpsStore()
    provider = CloudProvider(
        id="p3",
        type=ProviderType.AWS,
        name="A",
        base_url="http://a.example",
    )
    store.upsert_provider(provider)
    set_chaos("p3", ChaosKind.HEALTH_5XX, store=store)
    provider = store.get_provider("p3")
    assert provider is not None
    snap = asyncio.run(probe_provider(provider, store=store))
    assert snap.healthy is False
    assert snap.last_error == "chaos_health_5xx"


def test_probe_healthy_uses_policy_min_score() -> None:
    """Prober score floor comes from routing policy, not a hardcoded constant."""
    store = OpsStore()
    provider = CloudProvider(
        id="p_floor",
        type=ProviderType.HETZNER,
        name="H",
        base_url="http://h.example",
    )
    store.upsert_provider(provider)

    mock_response = MagicMock()
    mock_response.status_code = 200
    # High CPU pulls score below a raised floor but above the default 40.
    mock_response.json.return_value = {
        "status": "ok",
        "redis": "ok",
        "cpu_percent": 96.0,
        "mem_percent": 50.0,
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.ops.prober.httpx.AsyncClient", return_value=mock_client):
        snap_default = asyncio.run(probe_provider(provider, store=store))

    assert snap_default.score < 90.0
    assert snap_default.healthy is True

    policy = store.get_policy()
    policy.min_score_for_healthy = 99.0
    store.set_policy(policy)

    with patch("app.ops.prober.httpx.AsyncClient", return_value=mock_client):
        snap_raised = asyncio.run(probe_provider(provider, store=store))

    assert snap_raised.score == snap_default.score
    assert snap_raised.healthy is False
    assert snap_raised.score < policy.min_score_for_healthy
