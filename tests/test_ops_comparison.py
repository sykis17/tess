"""Comparison report tests."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.ops.comparison import run_comparison
from app.ops.models import (
    ChaosKind,
    CloudProvider,
    ComparisonRunRequest,
    HealthSnapshot,
    ProviderType,
)
from app.ops.store import OpsStore


def test_run_comparison_builds_report() -> None:
    store = OpsStore()
    for pid in ("x", "y"):
        store.upsert_provider(
            CloudProvider(
                id=pid,
                type=ProviderType.HETZNER,
                name=pid,
                base_url=f"http://{pid}.example",
            )
        )
        store.append_snapshot(
            HealthSnapshot(
                provider_id=pid,
                http_ok=True,
                score=70.0,
                healthy=True,
            )
        )
    store.routing.active_provider_id = "x"

    async def fake_probe(*, store=None, timeout_seconds=5.0):
        return [
            HealthSnapshot(provider_id="x", http_ok=True, score=70, healthy=True),
            HealthSnapshot(provider_id="y", http_ok=True, score=75, healthy=True),
        ]

    with patch("app.ops.comparison.probe_all_providers", side_effect=fake_probe):
        report = asyncio.run(
            run_comparison(
                ComparisonRunRequest(name="smoke", provider_ids=["x", "y"]),
                store=store,
            )
        )

    assert report.name == "smoke"
    assert "x" in report.provider_scores
    assert report.failover_ms is not None
    assert store.list_reports()
    assert any(e.event_type == "comparison_run" for e in store.list_events())


def test_comparison_with_chaos_injection() -> None:
    store = OpsStore()
    store.upsert_provider(
        CloudProvider(
            id="z",
            type=ProviderType.AWS,
            name="Z",
            base_url="http://z.example",
        )
    )
    store.routing.active_provider_id = "z"

    async def fake_probe(*, store=None, timeout_seconds=5.0):
        p = store.get_provider("z")
        assert p is not None
        assert p.chaos.kind == ChaosKind.MARK_UNHEALTHY
        return [
            HealthSnapshot(
                provider_id="z",
                http_ok=False,
                score=0,
                healthy=False,
                simulated=True,
            )
        ]

    with patch("app.ops.comparison.probe_all_providers", side_effect=fake_probe):
        report = asyncio.run(
            run_comparison(
                ComparisonRunRequest(
                    name="chaos",
                    provider_ids=["z"],
                    inject_chaos={"z": ChaosKind.MARK_UNHEALTHY},
                ),
                store=store,
            )
        )

    # Chaos cleared after run
    provider = store.get_provider("z")
    assert provider is not None
    assert provider.chaos.enabled is False
    assert any("injected" in n for n in report.notes)
