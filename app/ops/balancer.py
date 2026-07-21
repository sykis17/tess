"""Session assignment: share and performance-balance across providers."""

from __future__ import annotations

import hashlib

from app.ops.models import (
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

    if policy.preferred_provider_id:
        pref = ops.get_provider(policy.preferred_provider_id)
        if pref and pref.enabled:
            snap = ops.latest_snapshot(pref.id)
            if snap is None or (
                snap.healthy and snap.score >= policy.min_score_for_healthy
            ):
                return _finalize(pref.id)

    if policy.policy == RoutingPolicy.ACTIVE_ONLY:
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

    if policy == RoutingPolicy.SHARE:
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

    # ACTIVE_ONLY or unknown
    return provider_ids[0]


def seamless_migration_status() -> SeamlessMigrationStatus:
    """Explicit: failover v1 does not support seamless mid-session migrate."""
    return SeamlessMigrationStatus()
