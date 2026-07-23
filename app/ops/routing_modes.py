"""Dual and Performance routing mode transitions (mutually exclusive)."""

from __future__ import annotations

import logging

from app.ops.balancer import (
    challenger_beats_incumbent,
    dual_home_ids,
    next_best_provider_id,
    pick_best_provider_id,
)
from app.ops.models import (
    HealthSnapshot,
    OpsEvent,
    ProviderChangedMessage,
    RoutingPolicy,
    RoutingState,
    utc_now,
)
from app.ops.notify import publish_provider_changed
from app.ops.store import OpsStore, get_store, persist_store

logger = logging.getLogger(__name__)


def enable_dual(
    *,
    store: OpsStore | None = None,
    operator_id: str | None = None,
    peer_id: str | None = None,
) -> RoutingState:
    """
    Enable Dual: two concurrent sticky homes = active + next-best (or peer_id).

    Clears Performance if it was on. Requires ≥2 healthy online providers.
    """
    ops = store or get_store()
    routing = ops.get_routing()
    policy = ops.get_policy()

    active_id = routing.active_provider_id
    if not active_id:
        raise ValueError("no active provider — force active before enabling Dual")

    if peer_id:
        if peer_id == active_id:
            raise ValueError("dual peer must differ from active provider")
        peer = ops.get_provider(peer_id)
        if peer is None or not peer.enabled:
            raise ValueError(f"unknown or disabled peer: {peer_id}")
        snap = ops.latest_snapshot(peer_id)
        if snap is None or not snap.healthy or snap.score < policy.min_score_for_healthy:
            raise ValueError(f"peer is not healthy/online: {peer_id}")
        chosen_peer = peer_id
    else:
        chosen_peer = next_best_provider_id(ops, exclude={active_id})
        if not chosen_peer:
            raise ValueError(
                "Dual requires ≥2 healthy online providers (active + next-best)"
            )

    routing.dual_peer_id = chosen_peer
    routing.performance_challenger_id = None
    routing.performance_challenger_streak = 0
    routing.auto_wake_inflight_provider_id = None
    routing.auto_wake_inflight_at = None
    routing.auto_wake_inflight_task_id = None
    ops.set_routing(routing)

    new_policy = policy.model_copy(
        update={"policy": RoutingPolicy.DUAL, "auto_wake": False}
    )
    ops.set_policy(new_policy)

    details: dict = {
        "active": active_id,
        "peer": chosen_peer,
        "homes": [active_id, chosen_peer],
    }
    if operator_id:
        details["operator_id"] = operator_id
    ops.append_event(
        OpsEvent(event_type="dual_enabled", provider_id=active_id, details=details)
    )
    persist_store()
    return ops.get_routing()


def disable_dual(
    *,
    store: OpsStore | None = None,
    operator_id: str | None = None,
) -> RoutingState:
    """Exit Dual → ACTIVE_ONLY on current active; clear peer."""
    ops = store or get_store()
    routing = ops.get_routing()
    policy = ops.get_policy()
    previous_peer = routing.dual_peer_id
    routing.dual_peer_id = None
    ops.set_routing(routing)

    if policy.policy == RoutingPolicy.DUAL:
        ops.set_policy(policy.model_copy(update={"policy": RoutingPolicy.ACTIVE_ONLY}))

    details: dict = {"previous_peer": previous_peer}
    if operator_id:
        details["operator_id"] = operator_id
    ops.append_event(
        OpsEvent(
            event_type="dual_disabled",
            provider_id=routing.active_provider_id,
            details=details,
        )
    )
    persist_store()
    return ops.get_routing()


def enable_performance(
    *,
    store: OpsStore | None = None,
    operator_id: str | None = None,
    auto_wake: bool = False,
) -> RoutingState:
    """
    Enable Performance: single active, score-chase among online healthy providers.

    Clears Dual. When ``auto_wake`` is True, offline AWS/GCP standbys whose last
    known score would beat the incumbent may be woken via Celery (demo/ops).
    Default ``auto_wake=False`` keeps online-only behavior.
    """
    ops = store or get_store()
    routing = ops.get_routing()
    policy = ops.get_policy()

    routing.dual_peer_id = None
    routing.performance_challenger_id = None
    routing.performance_challenger_streak = 0
    if not auto_wake:
        routing.auto_wake_inflight_provider_id = None
        routing.auto_wake_inflight_at = None
        routing.auto_wake_inflight_task_id = None

    best = pick_best_provider_id(ops)
    if best and best != routing.active_provider_id:
        # Immediate switch to current best (operator intent); drop all sessions
        from app.ops.failover import _switch

        _switch(
            ops,
            routing,
            routing.active_provider_id,
            best,
            operator_id=operator_id,
            event_type="performance_switch",
        )
        routing = ops.get_routing()
    else:
        ops.set_routing(routing)

    ops.set_policy(
        policy.model_copy(
            update={"policy": RoutingPolicy.PERFORMANCE, "auto_wake": auto_wake}
        )
    )

    details: dict = {
        "active": ops.get_routing().active_provider_id,
        "auto_wake": auto_wake,
    }
    if operator_id:
        details["operator_id"] = operator_id
    ops.append_event(
        OpsEvent(
            event_type="performance_enabled",
            provider_id=ops.get_routing().active_provider_id,
            details=details,
        )
    )
    persist_store()

    if auto_wake:
        active_id = ops.get_routing().active_provider_id
        active_snap = ops.latest_snapshot(active_id) if active_id else None
        incumbent_score = active_snap.score if active_snap else 0.0
        from app.ops.standby_power import maybe_enqueue_auto_wake

        maybe_enqueue_auto_wake(store=ops, incumbent_score=incumbent_score)

    return ops.get_routing()


def disable_performance(
    *,
    store: OpsStore | None = None,
    operator_id: str | None = None,
) -> RoutingState:
    """Exit Performance → ACTIVE_ONLY frozen on current active (no preferred snap-back)."""
    ops = store or get_store()
    routing = ops.get_routing()
    policy = ops.get_policy()
    routing.performance_challenger_id = None
    routing.performance_challenger_streak = 0
    routing.auto_wake_inflight_provider_id = None
    routing.auto_wake_inflight_at = None
    routing.auto_wake_inflight_task_id = None
    ops.set_routing(routing)

    if policy.policy == RoutingPolicy.PERFORMANCE or policy.auto_wake:
        ops.set_policy(
            policy.model_copy(
                update={"policy": RoutingPolicy.ACTIVE_ONLY, "auto_wake": False}
            )
        )

    details: dict = {"frozen_active": routing.active_provider_id}
    if operator_id:
        details["operator_id"] = operator_id
    ops.append_event(
        OpsEvent(
            event_type="performance_disabled",
            provider_id=routing.active_provider_id,
            details=details,
        )
    )
    persist_store()
    return ops.get_routing()


def evaluate_dual_homes(
    snapshots: list[HealthSnapshot],
    *,
    store: OpsStore | None = None,
) -> ProviderChangedMessage | None:
    """
    When Dual is on: if a home fails past threshold, drop that home's sessions,
    backfill peer from next-best if available, else exit Dual to survivor.

    Locked: clear_assignments_for_provider(failed) only — never clear_assignments()
    for the whole Dual map, and never re-hash sticky sessions on the survivor.
    New peer only affects subsequent assign_session picks.
    """
    ops = store or get_store()
    policy = ops.get_policy()
    if policy.policy != RoutingPolicy.DUAL:
        return None

    routing = ops.get_routing()
    homes = dual_home_ids(ops)
    if not homes:
        return None

    failed_home: str | None = None
    for hid in homes:
        failures = routing.consecutive_failures.get(hid, 0)
        if failures >= policy.failure_threshold:
            failed_home = hid
            break

    if failed_home is None:
        return None

    survivor = next((h for h in homes if h != failed_home), None)
    if survivor is None:
        # Both gone somehow — keep active if set
        survivor = routing.active_provider_id
        if not survivor:
            return None

    dropped = ops.clear_assignments_for_provider(failed_home)
    routing.sessions_dropped_last = dropped
    routing.active_provider_id = survivor
    routing.last_failover_from = failed_home
    routing.last_failover_to = survivor
    routing.last_failover_at = utc_now()

    new_peer = next_best_provider_id(ops, exclude={survivor, failed_home})
    if new_peer:
        routing.dual_peer_id = new_peer
        ops.set_routing(routing)
        ops.append_event(
            OpsEvent(
                event_type="dual_home_lost",
                provider_id=survivor,
                details={
                    "failed": failed_home,
                    "survivor": survivor,
                    "new_peer": new_peer,
                    "sessions_dropped": dropped,
                },
            )
        )
        persist_store()
    else:
        routing.dual_peer_id = None
        ops.set_routing(routing)
        ops.set_policy(
            policy.model_copy(update={"policy": RoutingPolicy.ACTIVE_ONLY})
        )
        ops.append_event(
            OpsEvent(
                event_type="dual_degraded",
                provider_id=survivor,
                details={
                    "failed": failed_home,
                    "survivor": survivor,
                    "sessions_dropped": dropped,
                    "reason": "no_tertiary_peer",
                },
            )
        )
        persist_store()

    target = ops.get_provider(survivor)
    msg = ProviderChangedMessage(
        from_provider_id=failed_home,
        to_provider_id=survivor,
        sessions_dropped=dropped,
        ws_base_url=target.effective_ws_base_url() if target else None,
        message=(
            "Dual home lost — sessions on the failed home were dropped. "
            "Reconnect and resubmit if needed (seamless migration deferred)."
        ),
    )
    publish_provider_changed(msg)
    logger.warning(
        "Dual home lost %s -> survivor %s (dropped %s)",
        failed_home,
        survivor,
        dropped,
    )
    return msg


def evaluate_performance_chase(
    snapshots: list[HealthSnapshot],
    *,
    store: OpsStore | None = None,
) -> ProviderChangedMessage | None:
    """
    When Performance is on: switch active to best online score with anti-flap.

    Online providers always compete. When ``policy.auto_wake`` is True, may
    enqueue a wake for an offline standby whose last known score beats the
    incumbent (Celery; never blocks the probe loop).
    """
    ops = store or get_store()
    policy = ops.get_policy()
    if policy.policy != RoutingPolicy.PERFORMANCE:
        return None

    routing = ops.get_routing()
    snap_by_id = {s.provider_id: s for s in snapshots}
    active_id = routing.active_provider_id
    active_snap = (
        snap_by_id.get(active_id) or ops.latest_snapshot(active_id)
        if active_id
        else None
    )
    incumbent_score = active_snap.score if active_snap else 0.0

    if policy.auto_wake:
        from app.ops.standby_power import maybe_enqueue_auto_wake

        maybe_enqueue_auto_wake(store=ops, incumbent_score=incumbent_score)
        routing = ops.get_routing()

    best_id = pick_best_provider_id(ops, snaps_by_id=snap_by_id)

    if best_id is None:
        ops.set_routing(routing)
        persist_store()
        return None

    if best_id == active_id:
        routing.performance_challenger_id = None
        routing.performance_challenger_streak = 0
        # Clear inflight if this provider finished waking
        if routing.auto_wake_inflight_provider_id == active_id:
            routing.auto_wake_inflight_provider_id = None
            routing.auto_wake_inflight_at = None
            routing.auto_wake_inflight_task_id = None
        ops.set_routing(routing)
        persist_store()
        return None

    # Incumbent unhealthy → switch immediately (failover path may also handle)
    active_failures = (
        routing.consecutive_failures.get(active_id, 0) if active_id else 999
    )
    if active_id is None or active_failures >= policy.failure_threshold:
        from app.ops.failover import _switch

        return _switch(
            ops,
            routing,
            active_id,
            best_id,
            event_type="performance_switch",
        )

    best_snap = snap_by_id.get(best_id) or ops.latest_snapshot(best_id)
    if best_snap is None or active_snap is None:
        ops.set_routing(routing)
        persist_store()
        return None

    if not challenger_beats_incumbent(
        best_snap.score,
        active_snap.score,
        margin=policy.performance_score_margin,
    ):
        routing.performance_challenger_id = None
        routing.performance_challenger_streak = 0
        ops.set_routing(routing)
        persist_store()
        return None

    if routing.performance_challenger_id == best_id:
        routing.performance_challenger_streak += 1
    else:
        routing.performance_challenger_id = best_id
        routing.performance_challenger_streak = 1

    if routing.performance_challenger_streak < policy.performance_streak_required:
        ops.set_routing(routing)
        persist_store()
        return None

    routing.performance_challenger_id = None
    routing.performance_challenger_streak = 0
    from app.ops.failover import _switch

    return _switch(
        ops,
        routing,
        active_id,
        best_id,
        event_type="performance_switch",
    )
