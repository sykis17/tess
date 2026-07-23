"""Unit tests for standby power + Performance auto_wake."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.ops.models import (
    CloudProvider,
    HealthSnapshot,
    ProviderType,
    RoutingPolicy,
    RoutingPolicySettings,
)
from app.ops.routing_modes import enable_performance
from app.ops.standby_power import (
    AUTO_WAKE_INFLIGHT_TTL_S,
    clear_stale_auto_wake_inflight,
    enqueue_sleep_all_standbys,
    maybe_enqueue_auto_wake,
    pick_auto_wake_candidate,
    power_action_for_provider,
)
from app.ops.store import OpsStore


@pytest.fixture(autouse=True)
def _mute_provider_changed():
    with patch("app.ops.failover.publish_provider_changed"):
        yield


def _prov(
    pid: str,
    ptype: ProviderType,
    *,
    auto_wake_score_margin: float | None = None,
) -> CloudProvider:
    return CloudProvider(
        id=pid,
        type=ptype,
        name=pid,
        base_url=f"http://{pid}.example",
        auto_wake_score_margin=auto_wake_score_margin,
    )


def _snap(
    pid: str,
    *,
    healthy: bool,
    score: float,
    checked_at: datetime | None = None,
) -> HealthSnapshot:
    snap = HealthSnapshot(
        provider_id=pid,
        http_ok=healthy,
        latency_ms=40.0 if healthy else None,
        redis_ok=healthy,
        score=score,
        healthy=healthy,
    )
    if checked_at is not None:
        snap.checked_at = checked_at
    return snap


def _fleet() -> OpsStore:
    store = OpsStore()
    store.upsert_provider(_prov("hetz", ProviderType.HETZNER))
    store.upsert_provider(_prov("aws", ProviderType.AWS))
    store.upsert_provider(_prov("gcp", ProviderType.GCP))
    store.append_snapshot(_snap("hetz", healthy=True, score=70))
    store.append_snapshot(_snap("aws", healthy=False, score=95))
    store.append_snapshot(_snap("gcp", healthy=False, score=50))
    store.routing.active_provider_id = "hetz"
    return store


def test_pick_auto_wake_candidate_prefers_higher_last_score() -> None:
    store = _fleet()
    pid, details = pick_auto_wake_candidate(store, incumbent_score=70, margin=10)
    assert pid == "aws"
    assert details["picked"] == "aws"
    assert details["delta"] == pytest.approx(25.0)


def test_pick_auto_wake_skips_when_margin_not_met() -> None:
    store = _fleet()
    store.append_snapshot(_snap("hetz", healthy=True, score=90))
    pid, details = pick_auto_wake_candidate(store, incumbent_score=90, margin=10)
    assert pid is None
    assert details["reason"] == "no_fresh_candidate"


def test_pick_skips_already_healthy_standby() -> None:
    store = _fleet()
    store.append_snapshot(_snap("aws", healthy=True, score=95))
    pid, _ = pick_auto_wake_candidate(store, incumbent_score=70, margin=10)
    assert pid is None


def test_pick_refuses_stale_score() -> None:
    store = _fleet()
    stale = datetime.now(timezone.utc) - timedelta(hours=5)
    store.append_snapshot(_snap("aws", healthy=False, score=99, checked_at=stale))
    policy = store.get_policy()
    policy.auto_wake_max_score_age_s = 3600.0
    store.set_policy(policy)
    pid, details = pick_auto_wake_candidate(store, incumbent_score=70, margin=10)
    assert pid is None
    assert any(s.get("reason") == "stale_score" for s in details["skipped"])


def test_pick_respects_per_provider_margin() -> None:
    store = OpsStore()
    store.upsert_provider(_prov("hetz", ProviderType.HETZNER))
    # AWS needs +20 to wake; score only +15 over incumbent
    store.upsert_provider(
        _prov("aws", ProviderType.AWS, auto_wake_score_margin=20.0)
    )
    store.append_snapshot(_snap("hetz", healthy=True, score=70))
    store.append_snapshot(_snap("aws", healthy=False, score=85))
    store.routing.active_provider_id = "hetz"
    pid, details = pick_auto_wake_candidate(store, incumbent_score=70, margin=10)
    assert pid is None
    assert any(s.get("reason") == "margin_not_met" for s in details["skipped"])


def test_pick_skips_cooldown_provider() -> None:
    store = _fleet()
    routing = store.get_routing()
    routing.auto_wake_cooldown_until["aws"] = datetime.now(timezone.utc) + timedelta(
        minutes=10
    )
    store.set_routing(routing)
    pid, details = pick_auto_wake_candidate(store, incumbent_score=70, margin=10)
    assert pid is None
    assert any(s.get("reason") == "failure_cooldown" for s in details["skipped"])


def test_maybe_enqueue_auto_wake_respects_flag_off() -> None:
    store = _fleet()
    store.set_policy(
        RoutingPolicySettings(policy=RoutingPolicy.PERFORMANCE, auto_wake=False)
    )
    assert maybe_enqueue_auto_wake(store=store, incumbent_score=70) is None


def test_maybe_enqueue_auto_wake_sets_inflight() -> None:
    store = _fleet()
    store.set_policy(
        RoutingPolicySettings(policy=RoutingPolicy.PERFORMANCE, auto_wake=True)
    )
    with patch(
        "app.ops.standby_power.enqueue_standby_wake", return_value="task-1"
    ) as enq:
        pid = maybe_enqueue_auto_wake(store=store, incumbent_score=70)
    assert pid == "aws"
    enq.assert_called_once()
    routing = store.get_routing()
    assert routing.auto_wake_inflight_provider_id == "aws"
    assert routing.auto_wake_inflight_task_id == "task-1"
    assert routing.auto_wake_last_decision is not None
    assert "aws" in routing.auto_wake_last_decision

    with patch("app.ops.standby_power.enqueue_standby_wake") as enq2:
        assert maybe_enqueue_auto_wake(store=store, incumbent_score=70) is None
        enq2.assert_not_called()


def test_clear_stale_auto_wake_inflight() -> None:
    store = _fleet()
    routing = store.get_routing()
    routing.auto_wake_inflight_provider_id = "aws"
    routing.auto_wake_inflight_at = datetime.now(timezone.utc) - timedelta(
        seconds=AUTO_WAKE_INFLIGHT_TTL_S + 10
    )
    store.set_routing(routing)
    assert clear_stale_auto_wake_inflight(store) is True
    assert store.get_routing().auto_wake_inflight_provider_id is None
    assert "not an auto-sleep" in (store.get_routing().auto_wake_last_decision or "")


def test_wake_failure_clears_inflight_and_sets_cooldown() -> None:
    store = _fleet()
    routing = store.get_routing()
    routing.auto_wake_inflight_provider_id = "aws"
    routing.auto_wake_inflight_at = datetime.now(timezone.utc)
    store.set_routing(routing)
    store.set_policy(
        RoutingPolicySettings(
            policy=RoutingPolicy.PERFORMANCE,
            auto_wake=True,
            auto_wake_failure_cooldown_s=600,
        )
    )
    with patch(
        "app.ops.standby_power.run_standby_script",
        return_value={
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "creds missing",
            "action": "wake",
            "script": "aws_standby.py",
        },
    ), patch("app.ops.standby_power.get_store", return_value=store):
        result = power_action_for_provider("aws", "wake", store=store)

    assert result["ok"] is False
    routing = store.get_routing()
    assert routing.auto_wake_inflight_provider_id is None
    assert "aws" in routing.auto_wake_cooldown_until
    assert "Wake FAILED" in (routing.auto_wake_last_decision or "")
    assert any(
        e.event_type == "standby_wake_failed" for e in store.list_events()
    )


def test_intentional_sleep_event_distinct_from_failure() -> None:
    store = _fleet()
    with patch(
        "app.ops.standby_power.run_standby_script",
        return_value={
            "ok": True,
            "returncode": 0,
            "stdout": "stopped",
            "stderr": "",
            "action": "sleep",
            "script": "aws_standby.py",
        },
    ), patch("app.ops.standby_power.get_store", return_value=store):
        result = power_action_for_provider("aws", "sleep", store=store)

    assert result["ok"] is True
    types = [e.event_type for e in store.list_events()]
    assert "standby_sleep_intentional" in types
    assert "standby_sleep_failed" not in types
    assert "Intentional sleep" in (store.get_routing().auto_wake_last_decision or "")


def test_enable_performance_auto_wake_param() -> None:
    store = _fleet()
    with patch("app.ops.standby_power.enqueue_standby_wake", return_value="t"):
        enable_performance(store=store, auto_wake=True)
    assert store.get_policy().policy == RoutingPolicy.PERFORMANCE
    assert store.get_policy().auto_wake is True
    assert store.get_routing().auto_wake_inflight_provider_id == "aws"


def test_sleep_all_restores_active_only_and_enqueues_sleep() -> None:
    store = _fleet()
    store.set_policy(
        RoutingPolicySettings(policy=RoutingPolicy.PERFORMANCE, auto_wake=True)
    )
    routing = store.get_routing()
    routing.active_provider_id = "aws"
    routing.auto_wake_inflight_provider_id = "gcp"
    routing.auto_wake_cooldown_until["aws"] = datetime.now(timezone.utc) + timedelta(
        hours=1
    )
    store.set_routing(routing)

    with patch("app.ops.standby_power.get_store", return_value=store), patch(
        "app.ops.standby_power.enqueue_standby_sleep", return_value="sleep-task"
    ) as sleep_enq, patch("app.ops.failover.publish_provider_changed"):
        result = enqueue_sleep_all_standbys(operator_id="jesse")

    assert result["policy"] == "active_only"
    assert result["auto_wake"] is False
    assert result["severity"] == "intentional_resting_cost"
    assert result["active_provider_id"] == "hetz"
    assert sleep_enq.call_count == 2
    routing = store.get_routing()
    assert routing.auto_wake_inflight_provider_id is None
    assert routing.auto_wake_cooldown_until == {}
    assert "Intentional Sleep all" in (routing.auto_wake_last_decision or "")
