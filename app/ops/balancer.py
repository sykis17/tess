"""Session assignment: share, balance, dual homes, and performance-balance."""

from __future__ import annotations

import hashlib

from app.ops.models import (
    HealthSnapshot,
    OpsEvent,
    RoutingPolicy,
    SeamlessMigrationStatus,
    SessionAssignment,
)
from app.ops.store import OpsStore, get_store, persist_store


def list_healthy_provider_ids(store: OpsStore | None = None) -> list[str]:
    ops = store or get_store()
    policy = ops.get_policy()
    healthy: list[str] = []
    for provider in ops.list_providers():
        if not provider.enabled:
            continue
        if provider.org_id:
            # Customer BYO only used when explicitly preferred / assigned
            continue
        snap = ops.latest_snapshot(provider.id)
        if snap is None:
            # Unprobed but enabled — allow for share bootstrap
            healthy.append(provider.id)
            continue
        if snap.healthy and snap.score >= policy.min_score_for_healthy:
            healthy.append(provider.id)
    return healthy


def dual_home_ids(store: OpsStore | None = None) -> list[str]:
    """Return Dual chat homes (active + peer), filtered to non-empty unique ids."""
    ops = store or get_store()
    routing = ops.get_routing()
    homes: list[str] = []
    for pid in (routing.active_provider_id, routing.dual_peer_id):
        if pid and pid not in homes:
            homes.append(pid)
    return homes


def next_best_provider_id(
    store: OpsStore | None = None,
    *,
    exclude: set[str] | None = None,
) -> str | None:
    """
    Highest-score healthy online provider, excluding ``exclude``.

    Online-only: requires a snapshot (never invents / wakes stopped standbys).
    """
    ops = store or get_store()
    policy = ops.get_policy()
    skip = exclude or set()
    scored: list[tuple[float, float, str]] = []
    for provider in ops.list_providers():
        if not provider.enabled or provider.org_id:
            continue
        if provider.id in skip:
            continue
        snap = ops.latest_snapshot(provider.id)
        if snap is None:
            continue
        if not snap.healthy or snap.score < policy.min_score_for_healthy:
            continue
        latency = snap.latency_ms if snap.latency_ms is not None else 1e9
        scored.append((snap.score, -latency, provider.id))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][2]


def pick_best_provider_id(
    store: OpsStore | None = None,
    *,
    snaps_by_id: dict[str, HealthSnapshot] | None = None,
) -> str | None:
    """Best healthy online provider by score (ties: lower latency, then id)."""
    ops = store or get_store()
    policy = ops.get_policy()
    scored: list[tuple[float, float, str]] = []
    for provider in ops.list_providers():
        if not provider.enabled or provider.org_id:
            continue
        snap = (snaps_by_id or {}).get(provider.id) or ops.latest_snapshot(
            provider.id
        )
        if snap is None:
            continue
        if not snap.healthy or snap.score < policy.min_score_for_healthy:
            continue
        latency = snap.latency_ms if snap.latency_ms is not None else 1e9
        scored.append((snap.score, -latency, provider.id))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][2]


def challenger_beats_incumbent(
    challenger_score: float,
    incumbent_score: float,
    *,
    margin: float,
) -> bool:
    """Pure anti-flap gate: challenger must lead by at least ``margin``."""
    return challenger_score >= incumbent_score + margin


def assign_session(
    session_id: str,
    *,
    org_id: str | None = None,
    store: OpsStore | None = None,
    operator_id: str | None = None,
) -> SessionAssignment:
    """
    Assign a new session to a provider per routing policy.

    Sticky for the life of the session until failover clears assignments.
    """
    ops = store or get_store()
    existing = ops.get_assignment(session_id)
    if existing:
        return existing

    policy = ops.get_policy()
    routing = ops.get_routing()

    def _finalize(provider_id: str) -> SessionAssignment:
        assignment = SessionAssignment(
            session_id=session_id,
            provider_id=provider_id,
            policy=policy.policy,
        )
        ops.set_assignment(assignment)
        details: dict = {
            "session_id": session_id,
            "policy": policy.policy.value,
        }
        if operator_id:
            details["operator_id"] = operator_id
        ops.append_event(
            OpsEvent(
                event_type="session_assigned",
                provider_id=provider_id,
                details=details,
            )
        )
        persist_store()
        return assignment

    # Org-scoped customer pool
    if org_id:
        customer_ids = [
            p.id
            for p in ops.list_providers()
            if p.enabled and p.org_id == org_id
        ]
        if customer_ids:
            provider_id = _pick(ops, session_id, customer_ids, policy.policy)
            return _finalize(provider_id)

    if policy.preferred_provider_id and policy.policy not in (
        RoutingPolicy.DUAL,
        RoutingPolicy.PERFORMANCE,
    ):
        pref = ops.get_provider(policy.preferred_provider_id)
        if pref and pref.enabled:
            snap = ops.latest_snapshot(pref.id)
            if snap is None or (
                snap.healthy and snap.score >= policy.min_score_for_healthy
            ):
                return _finalize(pref.id)

    if policy.policy == RoutingPolicy.DUAL:
        homes = dual_home_ids(ops)
        if len(homes) < 2:
            # Degraded Dual — behave like active_only
            provider_id = routing.active_provider_id or (
                homes[0] if homes else None
            )
            if not provider_id:
                raise RuntimeError("no provider available for dual assignment")
            return _finalize(provider_id)
        return _finalize(_pick(ops, session_id, homes, RoutingPolicy.SHARE))

    if policy.policy in (RoutingPolicy.ACTIVE_ONLY, RoutingPolicy.PERFORMANCE):
        provider_id = routing.active_provider_id
        if not provider_id:
            healthy = list_healthy_provider_ids(ops)
            provider_id = healthy[0] if healthy else None
        if not provider_id:
            raise RuntimeError("no provider available for assignment")
        return _finalize(provider_id)

    healthy = list_healthy_provider_ids(ops)
    if not healthy:
        if routing.active_provider_id:
            healthy = [routing.active_provider_id]
        else:
            raise RuntimeError("no healthy providers for assignment")

    provider_id = _pick(ops, session_id, healthy, policy.policy)
    return _finalize(provider_id)


def _pick(
    ops: OpsStore,
    session_id: str,
    provider_ids: list[str],
    policy: RoutingPolicy,
) -> str:
    if len(provider_ids) == 1:
        return provider_ids[0]

    if policy in (RoutingPolicy.SHARE, RoutingPolicy.DUAL):
        # Stable hash stickiness + round-robin fallback diversity
        digest = int(hashlib.sha256(session_id.encode()).hexdigest(), 16)
        return provider_ids[digest % len(provider_ids)]

    if policy == RoutingPolicy.BALANCE:
        scored: list[tuple[float, str]] = []
        for pid in provider_ids:
            snap = ops.latest_snapshot(pid)
            score = snap.score if snap else 50.0
            # Mild round-robin jitter via index
            scored.append((score, pid))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Weighted: pick from top half by score using hash
        top = scored[: max(1, len(scored) // 2 + 1)]
        digest = int(hashlib.sha256(session_id.encode()).hexdigest(), 16)
        return top[digest % len(top)][1]

    # ACTIVE_ONLY / PERFORMANCE / unknown
    return provider_ids[0]


def seamless_migration_status() -> SeamlessMigrationStatus:
    """Explicit: failover v1 does not support seamless mid-session migrate."""
    return SeamlessMigrationStatus()
