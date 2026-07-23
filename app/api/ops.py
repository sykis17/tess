"""REST API for multi-cloud ops control plane."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.ops.admin_auth import require_admin
from app.ops.balancer import (
    assign_session,
    dual_home_ids,
    list_online_healthy_provider_ids,
    seamless_migration_status,
)
from app.ops.byo import register_customer_server
from app.ops.chaos import clear_chaos, set_chaos
from app.ops.comparison import run_comparison
from app.ops.failover import evaluate_failover, force_active_provider
from app.ops.health_logs import combined_health_logs
from app.ops.models import (
    ActiveRoutingResponse,
    ByoRegisterRequest,
    ChaosKind,
    CloudProvider,
    ComparisonReport,
    ComparisonRunRequest,
    OpsEvent,
    ProviderCreate,
    ProviderUpdate,
    RoutingPolicy,
    RoutingPolicySettings,
    new_id,
)
from app.ops.prober import probe_all_providers, probe_provider
from app.ops.routing_modes import (
    disable_dual,
    disable_performance,
    enable_dual,
    enable_performance,
)
from app.ops.store import get_store, persist_store
from app.providers.cloud import get_adapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"])

# Re-export for tests that import _check_admin from this module.
from app.ops.admin_auth import _check_admin  # noqa: E402

AdminOperator = Annotated[str, Depends(require_admin)]


@router.get("/providers")
async def list_providers(_operator_id: AdminOperator) -> list[CloudProvider]:
    return get_store().list_providers()


@router.post("/providers", status_code=201)
async def create_provider(
    body: ProviderCreate,
    operator_id: AdminOperator,
) -> CloudProvider:
    store = get_store()
    provider = CloudProvider(
        id=new_id("prov"),
        type=body.type,
        name=body.name,
        base_url=body.base_url,
        region=body.region,
        enabled=body.enabled,
        credentials_ref=body.credentials_ref,
        org_id=body.org_id,
        tags=body.tags,
        ws_base_url=body.ws_base_url,
    )
    validation = get_adapter(provider.type).validate_connection(provider)
    if not validation.get("ok"):
        raise HTTPException(status_code=400, detail=validation.get("message"))
    store.upsert_provider(provider)
    store.append_event(
        OpsEvent(
            event_type="provider_registered",
            provider_id=provider.id,
            details={
                "type": provider.type.value,
                "base_url": provider.base_url,
                "operator_id": operator_id,
            },
        )
    )
    persist_store()
    return provider


@router.get("/providers/{provider_id}")
async def get_provider(
    provider_id: str,
    _operator_id: AdminOperator,
) -> CloudProvider:
    provider = get_store().get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    return provider


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: str,
    body: ProviderUpdate,
    operator_id: AdminOperator,
) -> CloudProvider:
    store = get_store()
    provider = store.get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    data = body.model_dump(exclude_unset=True)
    updated = provider.model_copy(update=data)
    store.upsert_provider(updated)
    store.append_event(
        OpsEvent(
            event_type="provider_updated",
            provider_id=provider_id,
            details={"fields": sorted(data.keys()), "operator_id": operator_id},
        )
    )
    persist_store()
    return updated


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: str,
    operator_id: AdminOperator,
) -> None:
    store = get_store()
    if not store.delete_provider(provider_id):
        raise HTTPException(status_code=404, detail="provider not found")
    store.append_event(
        OpsEvent(
            event_type="provider_deleted",
            provider_id=provider_id,
            details={"operator_id": operator_id},
        )
    )
    persist_store()


@router.post("/providers/{provider_id}/connect")
async def connect_provider(
    provider_id: str,
    operator_id: AdminOperator,
) -> dict[str, Any]:
    """Validate adapter connection and run a health probe."""
    store = get_store()
    provider = store.get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    validation = get_adapter(provider.type).validate_connection(provider)
    snapshot = await probe_provider(provider, store=store)
    store.append_event(
        OpsEvent(
            event_type="provider_connect",
            provider_id=provider_id,
            details={
                "connected": bool(validation.get("ok") and snapshot.http_ok),
                "operator_id": operator_id,
            },
        )
    )
    persist_store()
    return {
        "validation": validation,
        "snapshot": snapshot,
        "connected": bool(validation.get("ok") and snapshot.http_ok),
    }


@router.post("/probe")
async def probe_now(
    operator_id: AdminOperator,
) -> dict[str, Any]:
    snapshots = await probe_all_providers()
    failover_msg = evaluate_failover(snapshots)
    get_store().append_event(
        OpsEvent(
            event_type="probe_manual",
            details={"operator_id": operator_id, "failover": bool(failover_msg)},
        )
    )
    persist_store()
    return {
        "snapshots": snapshots,
        "failover": failover_msg,
        "routing": get_store().get_routing(),
    }


@router.get("/health-logs")
async def get_health_logs(
    _operator_id: AdminOperator,
    provider_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return combined_health_logs(provider_id=provider_id, limit=limit)


@router.get("/events")
async def get_events(
    _operator_id: AdminOperator,
    provider_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[OpsEvent]:
    return get_store().list_events(
        provider_id=provider_id, event_type=event_type, limit=limit
    )


@router.get("/routing/notice")
async def get_routing_notice() -> dict[str, Any]:
    """Public minimal payload for frontend reconnect / provider-notice banner."""
    store = get_store()
    routing = store.get_routing()
    active = (
        store.get_provider(routing.active_provider_id)
        if routing.active_provider_id
        else None
    )
    return {
        "ws_base_url": active.effective_ws_base_url() if active else None,
        "sessions_dropped_last": routing.sessions_dropped_last,
    }


@router.get("/routing")
async def get_routing(_operator_id: AdminOperator) -> dict[str, Any]:
    from app.ops.standby_power import (
        clear_stale_auto_wake_inflight,
        expire_stale_power_actions,
    )

    store = get_store()
    # Soft-timeout stuck wakes so UI never sits forever on enqueue-only
    clear_stale_auto_wake_inflight(store)
    expire_stale_power_actions(store)
    routing = store.get_routing()
    policy = store.get_policy()
    active = (
        store.get_provider(routing.active_provider_id)
        if routing.active_provider_id
        else None
    )
    homes = dual_home_ids(store) if policy.policy == RoutingPolicy.DUAL else []
    healthy_online = list_online_healthy_provider_ids(store)
    return {
        "routing": routing,
        "policy": policy,
        "active": ActiveRoutingResponse(
            active_provider_id=routing.active_provider_id,
            policy=policy.policy,
            base_url=active.base_url if active else None,
            ws_base_url=active.effective_ws_base_url() if active else None,
            dual_peer_id=routing.dual_peer_id,
            dual_homes=homes,
        ),
        "healthy_online_ids": healthy_online,
        "dual_ready": len(healthy_online) >= 2,
        "power_by_provider": {
            pid: status.model_dump(mode="json")
            for pid, status in routing.power_by_provider.items()
        },
    }


@router.put("/routing/policy")
async def put_routing_policy(
    body: RoutingPolicySettings,
    operator_id: AdminOperator,
) -> RoutingPolicySettings:
    store = get_store()
    # XOR: putting DUAL/PERFORMANCE via raw policy clears the other mode's fields
    routing = store.get_routing()
    if body.policy == RoutingPolicy.DUAL:
        # Prefer dedicated POST /ops/routing/dual — but allow policy put if peer set
        if not routing.dual_peer_id:
            raise HTTPException(
                status_code=400,
                detail="Use POST /ops/routing/dual to enable Dual (sets peer home)",
            )
    elif body.policy != RoutingPolicy.DUAL:
        routing.dual_peer_id = None
    if body.policy != RoutingPolicy.PERFORMANCE:
        routing.performance_challenger_id = None
        routing.performance_challenger_streak = 0
        body = body.model_copy(update={"auto_wake": False})
    store.set_routing(routing)
    store.set_policy(body)
    details = body.model_dump(mode="json")
    details["operator_id"] = operator_id
    store.append_event(
        OpsEvent(
            event_type="policy_updated",
            details=details,
        )
    )
    persist_store()
    return body


@router.post("/routing/dual")
async def post_routing_dual(
    operator_id: AdminOperator,
    peer_id: str | None = None,
) -> dict[str, Any]:
    """Enable Dual mode (two concurrent chat homes). Clears Performance."""
    try:
        routing = enable_dual(operator_id=operator_id, peer_id=peer_id)
    except ValueError as exc:
        detail = str(exc)
        if "≥2 healthy" in detail or "not healthy" in detail:
            detail = (
                "Wake AWS or GCP first (need 2 healthy homes). "
                + detail
            )
        raise HTTPException(status_code=400, detail=detail) from exc
    store = get_store()
    return {
        "routing": routing,
        "policy": store.get_policy(),
        "dual_homes": dual_home_ids(store),
    }


@router.delete("/routing/dual")
async def delete_routing_dual(operator_id: AdminOperator) -> dict[str, Any]:
    """Exit Dual → active_only on current active."""
    routing = disable_dual(operator_id=operator_id)
    return {"routing": routing, "policy": get_store().get_policy()}


@router.post("/routing/performance")
async def post_routing_performance(
    operator_id: AdminOperator,
    auto_wake: bool = False,
) -> dict[str, Any]:
    """
    Enable Performance mode (score chase). Clears Dual.

    ``auto_wake=false`` (default): online-only — never starts stopped standbys.
    ``auto_wake=true``: may enqueue Celery wake for offline AWS/GCP whose last
    known score would beat the incumbent (requires cloud creds on the worker).
    """
    routing = enable_performance(operator_id=operator_id, auto_wake=auto_wake)
    policy = get_store().get_policy()
    return {
        "routing": routing,
        "policy": policy,
        "auto_wake": policy.auto_wake,
    }


@router.delete("/routing/performance")
async def delete_routing_performance(operator_id: AdminOperator) -> dict[str, Any]:
    """Exit Performance → active_only frozen on current active; clears auto_wake."""
    routing = disable_performance(operator_id=operator_id)
    return {"routing": routing, "policy": get_store().get_policy()}


@router.post("/providers/{provider_id}/wake")
async def wake_provider(
    provider_id: str,
    operator_id: AdminOperator,
) -> dict[str, Any]:
    """Enqueue wake for an AWS/GCP standby (Celery → scripts/*_standby.py wake)."""
    from app.ops.standby_power import (
        enqueue_standby_wake,
        is_standby_provider,
        script_for_provider,
    )

    store = get_store()
    provider = store.get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    if not is_standby_provider(provider) or script_for_provider(provider) is None:
        raise HTTPException(
            status_code=400,
            detail="only AWS/GCP standbys support wake",
        )
    task_id = enqueue_standby_wake(
        provider_id, operator_id=operator_id, store=store
    )
    if task_id is not None:
        store.append_event(
            OpsEvent(
                event_type="standby_wake_enqueued",
                provider_id=provider_id,
                details={"task_id": task_id, "operator_id": operator_id},
            )
        )
        persist_store()
    power = store.get_routing().power_by_provider.get(provider_id)
    return {
        "status": "enqueued" if task_id else "completed_inline",
        "provider_id": provider_id,
        "task_id": task_id,
        "power": power.model_dump(mode="json") if power else None,
        "message": (
            "Wake started in background; watch power badge / trail for "
            "standby_wake or Wake FAILED (enqueue alone is not done)"
            if task_id
            else "Wake finished inline (no Celery); see trail for terminal status"
        ),
    }


@router.post("/providers/{provider_id}/sleep")
async def sleep_provider(
    provider_id: str,
    operator_id: AdminOperator,
) -> dict[str, Any]:
    """Enqueue sleep/stop for an AWS/GCP standby (cost control)."""
    from app.ops.standby_power import (
        enqueue_standby_sleep,
        is_standby_provider,
        script_for_provider,
    )

    store = get_store()
    provider = store.get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    if not is_standby_provider(provider) or script_for_provider(provider) is None:
        raise HTTPException(
            status_code=400,
            detail="only AWS/GCP standbys support sleep",
        )
    task_id = enqueue_standby_sleep(
        provider_id, operator_id=operator_id, store=store
    )
    if task_id is not None:
        store.append_event(
            OpsEvent(
                event_type="standby_sleep_enqueued",
                provider_id=provider_id,
                details={"task_id": task_id, "operator_id": operator_id},
            )
        )
        persist_store()
    power = store.get_routing().power_by_provider.get(provider_id)
    return {
        "status": "enqueued" if task_id else "completed_inline",
        "provider_id": provider_id,
        "task_id": task_id,
        "power": power.model_dump(mode="json") if power else None,
        "message": (
            "Sleep started in background; watch trail for intentional sleep "
            "or Sleep FAILED"
            if task_id
            else "Sleep finished inline (no Celery); see trail for terminal status"
        ),
    }


@router.post("/standbys/sleep-all")
async def sleep_all_standbys(operator_id: AdminOperator) -> dict[str, Any]:
    """
    Resting cost posture: exit Dual/Performance, force Hetzner active, sleep
    all AWS/GCP standbys. Use after demos so nothing is left burning cost.
    """
    from app.ops.standby_power import enqueue_sleep_all_standbys

    return enqueue_sleep_all_standbys(operator_id=operator_id)


@router.post("/routing/active/{provider_id}")
async def set_active(
    provider_id: str,
    operator_id: AdminOperator,
) -> dict[str, Any]:
    try:
        msg = force_active_provider(provider_id, operator_id=operator_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"failover": msg, "routing": get_store().get_routing()}


@router.post("/sessions/{session_id}/assign")
async def assign_session_route(
    session_id: str,
    operator_id: AdminOperator,
    org_id: str | None = None,
) -> dict[str, Any]:
    try:
        assignment = assign_session(
            session_id, org_id=org_id, operator_id=operator_id
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    provider = get_store().get_provider(assignment.provider_id)
    return {
        "assignment": assignment,
        "ws_base_url": provider.effective_ws_base_url() if provider else None,
        "base_url": provider.base_url if provider else None,
    }


@router.get("/seamless-migration")
async def get_seamless_migration(_operator_id: AdminOperator) -> dict[str, Any]:
    status = seamless_migration_status()
    return status.model_dump()


@router.post("/chaos/{provider_id}")
async def inject_chaos(
    provider_id: str,
    operator_id: AdminOperator,
    kind: ChaosKind,
    latency_ms: float = 2500.0,
) -> dict[str, Any]:
    try:
        chaos = set_chaos(
            provider_id, kind, latency_ms=latency_ms, operator_id=operator_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"provider_id": provider_id, "chaos": chaos}


@router.delete("/chaos/{provider_id}")
async def remove_chaos(
    provider_id: str,
    operator_id: AdminOperator,
) -> dict[str, str]:
    try:
        clear_chaos(provider_id, operator_id=operator_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "cleared"}


@router.post("/providers/{provider_id}/simulate-unhealthy")
async def simulate_unhealthy(
    provider_id: str,
    operator_id: AdminOperator,
    enabled: bool = True,
) -> CloudProvider:
    store = get_store()
    provider = store.get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    if enabled:
        set_chaos(
            provider_id,
            ChaosKind.MARK_UNHEALTHY,
            store=store,
            operator_id=operator_id,
        )
    else:
        clear_chaos(provider_id, store=store, operator_id=operator_id)
    updated = store.get_provider(provider_id)
    assert updated is not None
    return updated


@router.post("/compare", status_code=201)
async def compare_providers(
    body: ComparisonRunRequest,
    operator_id: AdminOperator,
) -> ComparisonReport:
    return await run_comparison(body, operator_id=operator_id)


@router.get("/compare")
async def list_comparisons(_operator_id: AdminOperator) -> list[ComparisonReport]:
    return get_store().list_reports()


@router.post("/byo", status_code=201)
async def register_byo(
    body: ByoRegisterRequest,
    operator_id: AdminOperator,
) -> CloudProvider:
    try:
        return await register_customer_server(body, operator_id=operator_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
