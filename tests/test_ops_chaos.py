"""Chaos injection and simulated unhealthy tests."""

from app.ops.chaos import clear_chaos, set_chaos
from app.ops.models import ChaosKind, CloudProvider, ProviderType
from app.ops.store import OpsStore


def test_set_and_clear_chaos() -> None:
    store = OpsStore()
    store.upsert_provider(
        CloudProvider(
            id="h1",
            type=ProviderType.HETZNER,
            name="H",
            base_url="http://h.example",
        )
    )
    chaos = set_chaos("h1", ChaosKind.HIGH_LATENCY, latency_ms=3000, store=store)
    assert chaos.enabled is True
    provider = store.get_provider("h1")
    assert provider is not None
    assert provider.chaos.kind == ChaosKind.HIGH_LATENCY

    clear_chaos("h1", store=store)
    provider = store.get_provider("h1")
    assert provider is not None
    assert provider.chaos.enabled is False
    events = store.list_events(provider_id="h1")
    assert any(e.event_type.startswith("chaos_") for e in events)


def test_mark_unhealthy_sets_simulate_flag() -> None:
    store = OpsStore()
    store.upsert_provider(
        CloudProvider(
            id="h2",
            type=ProviderType.AWS,
            name="A",
            base_url="http://a.example",
        )
    )
    set_chaos("h2", ChaosKind.MARK_UNHEALTHY, store=store)
    provider = store.get_provider("h2")
    assert provider is not None
    assert provider.simulate_unhealthy is True
