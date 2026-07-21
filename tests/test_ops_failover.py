"""Unit tests for failover with intentional session drop."""

from unittest.mock import patch

import pytest

from app.ops.failover import evaluate_failover, force_active_provider
from app.ops.models import CloudProvider, HealthSnapshot, ProviderType, SessionAssignment
from app.ops.store import OpsStore


@pytest.fixture(autouse=True)
def _mute_provider_changed_publish():
    with patch("app.ops.failover.publish_provider_changed"):
        yield


def _provider(pid: str, name: str = "p") -> CloudProvider:
    return CloudProvider(
        id=pid,
        type=ProviderType.HETZNER,
        name=name,
        base_url=f"http://{pid}.example",
    )


def _snap(pid: str, *, healthy: bool, score: float) -> HealthSnapshot:
    return HealthSnapshot(
        provider_id=pid,
        http_ok=healthy,
        latency_ms=50.0 if healthy else None,
        redis_ok=True if healthy else False,
        score=score,
        healthy=healthy,
    )


def test_failover_switches_after_threshold() -> None:
    store = OpsStore()
    store.upsert_provider(_provider("a", "A"))
    store.upsert_provider(_provider("b", "B"))
    store.routing.active_provider_id = "a"
    policy = store.get_policy()
    policy.failure_threshold = 2
    policy.recovery_threshold = 1
    store.set_policy(policy)
    store.set_assignment(
        SessionAssignment(session_id="s1", provider_id="a", policy=policy.policy)
    )

    # First unhealthy — no switch yet
    msg = evaluate_failover([_snap("a", healthy=False, score=0), _snap("b", healthy=True, score=90)], store=store)
    assert msg is None
    assert store.get_routing().active_provider_id == "a"

    # Second unhealthy — switch, drop sessions
    msg = evaluate_failover([_snap("a", healthy=False, score=0), _snap("b", healthy=True, score=90)], store=store)
    assert msg is not None
    assert msg.from_provider_id == "a"
    assert msg.to_provider_id == "b"
    assert msg.sessions_dropped == 1
    assert store.get_assignment("s1") is None
    assert store.get_routing().active_provider_id == "b"


def test_force_active_drops_sessions() -> None:
    store = OpsStore()
    store.upsert_provider(_provider("a"))
    store.upsert_provider(_provider("b"))
    store.routing.active_provider_id = "a"
    store.set_assignment(
        SessionAssignment(
            session_id="s2",
            provider_id="a",
            policy=store.get_policy().policy,
        )
    )
    msg = force_active_provider("b", store=store)
    assert msg.to_provider_id == "b"
    assert msg.sessions_dropped == 1


def test_no_failover_without_standby() -> None:
    store = OpsStore()
    store.upsert_provider(_provider("solo"))
    store.routing.active_provider_id = "solo"
    policy = store.get_policy()
    policy.failure_threshold = 1
    store.set_policy(policy)

    msg = evaluate_failover([_snap("solo", healthy=False, score=0)], store=store)
    assert msg is None
    assert store.get_routing().active_provider_id == "solo"
    events = store.list_events(event_type="failover_blocked")
    assert len(events) >= 1
