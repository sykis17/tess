"""Unit tests for Dual (two homes) XOR Performance routing."""

from unittest.mock import patch

import pytest

from app.ops.balancer import (
    assign_session,
    challenger_beats_incumbent,
    dual_home_ids,
    next_best_provider_id,
    pick_best_provider_id,
)
from app.ops.failover import evaluate_failover
from app.ops.models import (
    CloudProvider,
    HealthSnapshot,
    ProviderType,
    RoutingPolicy,
    RoutingPolicySettings,
    SessionAssignment,
)
from app.ops.routing_modes import (
    disable_dual,
    disable_performance,
    enable_dual,
    enable_performance,
)
from app.ops.store import OpsStore


@pytest.fixture(autouse=True)
def _mute_provider_changed_publish():
    with patch("app.ops.failover.publish_provider_changed"), patch(
        "app.ops.routing_modes.publish_provider_changed"
    ):
        yield


def _provider(pid: str, name: str | None = None) -> CloudProvider:
    return CloudProvider(
        id=pid,
        type=ProviderType.HETZNER,
        name=name or pid,
        base_url=f"http://{pid}.example",
    )


def _snap(
    pid: str,
    *,
    healthy: bool = True,
    score: float = 80.0,
    latency_ms: float = 50.0,
) -> HealthSnapshot:
    return HealthSnapshot(
        provider_id=pid,
        http_ok=healthy,
        latency_ms=latency_ms if healthy else None,
        redis_ok=True if healthy else False,
        score=score,
        healthy=healthy,
    )


def _three_healthy() -> OpsStore:
    store = OpsStore()
    for pid, score in (("a", 70.0), ("b", 90.0), ("c", 60.0)):
        store.upsert_provider(_provider(pid))
        store.append_snapshot(_snap(pid, score=score))
    store.routing.active_provider_id = "a"
    return store


def test_challenger_beats_incumbent_margin() -> None:
    assert challenger_beats_incumbent(80, 70, margin=10) is True
    assert challenger_beats_incumbent(79, 70, margin=10) is False


def test_next_best_excludes_active() -> None:
    store = _three_healthy()
    assert next_best_provider_id(store, exclude={"a"}) == "b"


def test_pick_best_by_score() -> None:
    store = _three_healthy()
    assert pick_best_provider_id(store) == "b"


def test_enable_dual_sets_peer_and_policy() -> None:
    store = _three_healthy()
    routing = enable_dual(store=store)
    assert store.get_policy().policy == RoutingPolicy.DUAL
    assert routing.dual_peer_id == "b"  # next-best vs active a
    assert dual_home_ids(store) == ["a", "b"]


def test_enable_dual_requires_two_healthy() -> None:
    store = OpsStore()
    store.upsert_provider(_provider("solo"))
    store.append_snapshot(_snap("solo", score=90))
    store.routing.active_provider_id = "solo"
    with pytest.raises(ValueError, match="≥2"):
        enable_dual(store=store)


def test_dual_assign_sticky_hash_over_two_homes() -> None:
    store = _three_healthy()
    enable_dual(store=store)
    ids = {assign_session(f"sess-{i}", store=store).provider_id for i in range(40)}
    assert ids <= {"a", "b"}
    assert "c" not in ids
    # With 40 sessions, hash should usually hit both homes
    assert len(ids) >= 1


def test_dual_xor_performance() -> None:
    store = _three_healthy()
    enable_dual(store=store)
    assert store.get_policy().policy == RoutingPolicy.DUAL
    enable_performance(store=store)
    assert store.get_policy().policy == RoutingPolicy.PERFORMANCE
    assert store.get_routing().dual_peer_id is None
    # Best score becomes active
    assert store.get_routing().active_provider_id == "b"
    enable_dual(store=store)
    assert store.get_policy().policy == RoutingPolicy.DUAL
    assert store.get_routing().dual_peer_id is not None


def test_disable_dual_restores_active_only() -> None:
    store = _three_healthy()
    enable_dual(store=store)
    disable_dual(store=store)
    assert store.get_policy().policy == RoutingPolicy.ACTIVE_ONLY
    assert store.get_routing().dual_peer_id is None


def test_disable_performance_freezes_active() -> None:
    store = _three_healthy()
    enable_performance(store=store)
    assert store.get_routing().active_provider_id == "b"
    disable_performance(store=store)
    assert store.get_policy().policy == RoutingPolicy.ACTIVE_ONLY
    assert store.get_routing().active_provider_id == "b"


def test_dual_home_loss_backfills_peer() -> None:
    store = _three_healthy()
    enable_dual(store=store)  # homes a, b
    policy = store.get_policy()
    policy.failure_threshold = 2
    store.set_policy(policy)
    store.set_assignment(
        SessionAssignment(
            session_id="on-a", provider_id="a", policy=RoutingPolicy.DUAL
        )
    )
    store.set_assignment(
        SessionAssignment(
            session_id="on-b", provider_id="b", policy=RoutingPolicy.DUAL
        )
    )

    snaps = [
        _snap("a", healthy=False, score=0),
        _snap("b", healthy=True, score=90),
        _snap("c", healthy=True, score=60),
    ]
    assert evaluate_failover(snaps, store=store) is None
    msg = evaluate_failover(snaps, store=store)
    assert msg is not None
    assert msg.from_provider_id == "a"
    assert msg.to_provider_id == "b"
    assert store.get_assignment("on-a") is None
    assert store.get_assignment("on-b") is not None
    routing = store.get_routing()
    assert routing.active_provider_id == "b"
    assert routing.dual_peer_id == "c"
    assert store.get_policy().policy == RoutingPolicy.DUAL


def test_dual_home_loss_degrades_without_tertiary() -> None:
    store = OpsStore()
    store.upsert_provider(_provider("a"))
    store.upsert_provider(_provider("b"))
    store.append_snapshot(_snap("a", score=70))
    store.append_snapshot(_snap("b", score=90))
    store.routing.active_provider_id = "a"
    enable_dual(store=store)
    policy = store.get_policy()
    policy.failure_threshold = 1
    store.set_policy(policy)

    snaps = [
        _snap("a", healthy=False, score=0),
        _snap("b", healthy=True, score=90),
    ]
    msg = evaluate_failover(snaps, store=store)
    assert msg is not None
    assert store.get_routing().active_provider_id == "b"
    assert store.get_routing().dual_peer_id is None
    assert store.get_policy().policy == RoutingPolicy.ACTIVE_ONLY


def test_performance_anti_flap_requires_streak() -> None:
    store = _three_healthy()
    # Start with a active at 70; b at 90
    store.routing.active_provider_id = "a"
    enable_performance(store=store)
    # enable_performance already switched to b — reset to a for flap test
    store.routing.active_provider_id = "a"
    store.set_routing(store.routing)
    policy = store.get_policy()
    policy.performance_score_margin = 10
    policy.performance_streak_required = 2
    store.set_policy(policy)

    snaps = [
        _snap("a", score=70),
        _snap("b", score=90),
        _snap("c", score=60),
    ]
    # First probe: streak builds, no switch
    msg = evaluate_failover(snaps, store=store)
    assert msg is None
    assert store.get_routing().active_provider_id == "a"
    assert store.get_routing().performance_challenger_streak == 1

    # Second probe: switch
    msg = evaluate_failover(snaps, store=store)
    assert msg is not None
    assert msg.to_provider_id == "b"
    assert store.get_routing().active_provider_id == "b"


def test_performance_no_switch_below_margin() -> None:
    store = OpsStore()
    store.upsert_provider(_provider("a"))
    store.upsert_provider(_provider("b"))
    store.append_snapshot(_snap("a", score=80))
    store.append_snapshot(_snap("b", score=85))  # only +5
    store.routing.active_provider_id = "a"
    policy = store.get_policy()
    policy.policy = RoutingPolicy.PERFORMANCE
    policy.performance_score_margin = 10
    policy.performance_streak_required = 1
    store.set_policy(policy)

    snaps = [_snap("a", score=80), _snap("b", score=85)]
    msg = evaluate_failover(snaps, store=store)
    assert msg is None
    assert store.get_routing().active_provider_id == "a"
