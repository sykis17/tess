"""Automatic failover / switchover with flap protection."""

from __future__ import annotations

import logging

from app.ops.models import (
    HealthSnapshot,
    OpsEvent,
    ProviderChangedMessage,
    RoutingState,
)
from app.ops.notify import publish_provider_changed
from app.ops.store import OpsStore, get_store, persist_store

logger = logging.getLogger(__name__)


def evaluate_failover(
    snapshots: list[HealthSnapshot],
    *,
    store: OpsStore | None = None,
) -> ProviderChangedMessage | None:
    """
    Update consecutive failure/success counters and switch active provider.

    Failover v1 intentionally drops in-flight sessions — returns a
    ProviderChangedMessage when a switch occurs (caller notifies clients).
    """
    ops = store or get_store()
    policy = ops.get_policy()
    if not policy.auto_failover:
        return None

    routing = ops.get_routing()
    snap_by_id = {s.provider_id: s for s in snapshots}

    for provider in ops.list_providers():
        if not provider.enabled:
            continue
        snap = snap_by_id.get(provider.id) or ops.latest_snapshot(provider.id)
        if snap is None:
            continue

        pid = provider.id
        failures = routing.consecutive_failures.get(pid, 0)
        successes = routing.consecutive_successes.get(pid, 0)

        unhealthy = (
            not snap.healthy
            or snap.score < policy.min_score_for_healthy
            or (
                snap.latency_ms is not None
                and snap.latency_ms > policy.latency_p95_threshold_ms
            )
        )

        if unhealthy:
            failures += 1
            successes = 0
        else:
            successes += 1
            failures = 0

        routing.consecutive_failures[pid] = failures
        routing.consecutive_successes[pid] = successes

    active_id = routing.active_provider_id
    active_failures = (
        routing.consecutive_failures.get(active_id, 0) if active_id else 999
    )
    needs_failover = active_id is None or active_failures >= policy.failure_threshold

    if not needs_failover:
        # Failback: if preferred or previous standby is healthy enough, optional
        preferred = policy.preferred_provider_id
        if preferred and preferred != active_id:
            pref_ok = routing.consecutive_successes.get(preferred, 0)
            if pref_ok >= policy.recovery_threshold:
                return _switch(ops, routing, active_id, preferred)
        ops.set_routing(routing)
        persist_store()
        return None

    candidates = []
    for provider in ops.list_providers():
        if not provider.enabled:
            continue
        if provider.id == active_id:
            continue
        successes = routing.consecutive_successes.get(provider.id, 0)
        failures = routing.consecutive_failures.get(provider.id, 0)
        snap = snap_by_id.get(provider.id) or ops.latest_snapshot(provider.id)
        if snap is None:
            continue
        if not snap.healthy or snap.score < policy.min_score_for_healthy:
            continue
        # Accept currently healthy standbys; require recovery streak only if
        # they recently failed.
        if failures > 0 and successes < policy.recovery_threshold:
            continue
        candidates.append((snap.score, provider.id))

    if not candidates:
        ops.set_routing(routing)
        persist_store()
        ops.append_event(
            OpsEvent(
                event_type="failover_blocked",
                provider_id=active_id,
                details={"reason": "no_healthy_standby"},
            )
        )
        return None

    candidates.sort(reverse=True)
    target_id = candidates[0][1]
    return _switch(ops, routing, active_id, target_id)


def _switch(
    ops: OpsStore,
    routing: RoutingState,
    from_id: str | None,
    to_id: str,
    *,
    operator_id: str | None = None,
) -> ProviderChangedMessage:
    dropped = ops.clear_assignments()

    routing.last_failover_from = from_id
    routing.last_failover_to = to_id
    routing.active_provider_id = to_id
    routing.sessions_dropped_last = dropped
    from app.ops.models import utc_now

    routing.last_failover_at = utc_now()
    ops.set_routing(routing)

    target = ops.get_provider(to_id)
    msg = ProviderChangedMessage(
        from_provider_id=from_id,
        to_provider_id=to_id,
        sessions_dropped=dropped,
        ws_base_url=target.effective_ws_base_url() if target else None,
    )
    details: dict = {
        "from": from_id,
        "to": to_id,
        "sessions_dropped": dropped,
        "message": msg.message,
    }
    if operator_id:
        details["operator_id"] = operator_id
    ops.append_event(
        OpsEvent(
            event_type="failover",
            provider_id=to_id,
            details=details,
        )
    )
    persist_store()
    publish_provider_changed(msg)
    logger.warning(
        "Failover %s -> %s (dropped %s sessions)", from_id, to_id, dropped
    )
    return msg


def force_active_provider(
    provider_id: str,
    *,
    store: OpsStore | None = None,
    operator_id: str | None = None,
) -> ProviderChangedMessage:
    """Admin override of active provider (still drops in-flight sessions)."""
    ops = store or get_store()
    provider = ops.get_provider(provider_id)
    if provider is None:
        raise ValueError(f"unknown provider: {provider_id}")
    routing = ops.get_routing()
    return _switch(
        ops,
        routing,
        routing.active_provider_id,
        provider_id,
        operator_id=operator_id,
    )
