"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.ops import router as ops_router
from app.api import ws_router
from app.core.config import settings
from app.core.egress_guard import verify_posture_or_raise
from app.ops import metrics
from app.ops.bootstrap import bootstrap_ops_control_plane
from app.ops.failover import evaluate_failover
from app.ops.fencing import (
    FenceError,
    clear_demote_callbacks,
    demote,
    get_role_state,
    mark_primary,
    mark_standby,
    register_demote_callback,
    set_ha_disabled_role,
    write_fence,
)
from app.ops.prober import probe_all_providers
from app.ops.store import promote_fence, restore_store

logger = logging.getLogger(__name__)

_probe_task: asyncio.Task[None] | None = None
_campaign_task: asyncio.Task[None] | None = None
_held_lease_id: int | None = None


async def _ops_probe_loop() -> None:
    """Background health probes + failover evaluation (primary only)."""
    interval = max(5.0, settings.ops_probe_interval_seconds)
    while True:
        try:
            role = get_role_state()
            if settings.ops_ha_active() and role.role != "primary":
                await asyncio.sleep(interval)
                continue
            snapshots = await probe_all_providers()
            term = role.fence_term if role.role == "primary" else 0
            with write_fence(term or 0):
                msg = evaluate_failover(snapshots)
            if msg:
                logger.warning(
                    "Provider failover: %s -> %s (dropped=%s)",
                    msg.from_provider_id,
                    msg.to_provider_id,
                    msg.sessions_dropped,
                )
        except asyncio.CancelledError:
            raise
        except FenceError:
            logger.exception("Ops probe loop fence error")
        except Exception:
            logger.exception("Ops probe loop error")
        await asyncio.sleep(interval)


def _stop_probe_loop(reason: str) -> None:
    global _probe_task
    _ = reason
    task = _probe_task
    if task is not None and not task.done():
        task.cancel()


def _ensure_probe_loop() -> None:
    global _probe_task
    if not settings.ops_probe_enabled:
        return
    if _probe_task is None or _probe_task.done():
        _probe_task = asyncio.create_task(_ops_probe_loop())


async def _on_become_primary(fence_term: int, lease_id: int) -> None:
    global _held_lease_id
    _held_lease_id = lease_id
    # Root span for the promotion path (fires only on an actual promotion — rare).
    with metrics.get_tracer().start_as_current_span("ops.promotion") as _sp:
        _sp.set_attribute("ops.instance_id", settings.ops_cp_instance_id)
        _sp.set_attribute("ops.fence_term", int(fence_term))
        _sp.set_attribute("ops.lease_id", int(lease_id))
        mark_primary(fence_term, lease_id)
        try:
            with metrics.get_tracer().start_as_current_span("ops.promote_fence"):
                promote_fence(fence_term)
        except FenceError as exc:
            metrics.record_fence_reject(metrics.fence_error_kind(exc), "campaign")
            demote("redis_promote_fence_failed")
            raise
        restore_store(raise_on_error=False)
        with write_fence(fence_term):
            from app.ops.store import persist_store

            try:
                with metrics.get_tracer().start_as_current_span("ops.initial_persist"):
                    persist_store(fence_term=fence_term)
            except FenceError as exc:
                metrics.record_fence_reject(metrics.fence_error_kind(exc), "campaign")
                demote("primary_initial_persist_failed")
                raise
        _ensure_probe_loop()
        _sp.set_attribute("ops.outcome", "primary_ready")
        logger.warning(
            "CP primary ready instance=%s fence_term=%s",
            settings.ops_cp_instance_id,
            fence_term,
        )


async def _campaign_loop() -> None:
    """Campaign for etcd lease; keepalive while primary; demote on loss."""
    global _held_lease_id
    from app.ops.consensus import get_consensus_backend

    backend = get_consensus_backend()
    interval = max(0.5, settings.ops_etcd_campaign_interval_seconds)
    ttl = max(5, int(settings.ops_etcd_lease_ttl_seconds))
    instance_id = settings.ops_cp_instance_id

    while True:
        try:
            role = get_role_state()
            if role.role == "primary" and _held_lease_id is not None:
                ok = await asyncio.to_thread(backend.keepalive, _held_lease_id)
                if ok:
                    metrics.record_lease_keepalive("ok")
                    metrics.set_lease_ttl(ttl)
                else:
                    metrics.record_lease_keepalive("failed")
                    demote("lease_keepalive_failed")
                    _held_lease_id = None
                    mark_standby()
                await asyncio.sleep(max(1.0, ttl / 3))
                continue

            live = await asyncio.to_thread(backend.read_election)
            if live.leader == instance_id and role.role != "primary":
                # We appear as leader in etcd but lost local role — re-campaign.
                pass

            term = await asyncio.to_thread(
                backend.try_campaign, instance_id, ttl
            )
            if term is not None:
                lease_id = getattr(backend, "_lease_id", None) or 0
                await _on_become_primary(term, int(lease_id))
            else:
                live = await asyncio.to_thread(backend.read_election)
                mark_standby(
                    primary_instance_id=live.leader,
                    fence_term=live.fence_term,
                )
                _stop_probe_loop("standby")
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("CP campaign loop error")
            await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _probe_task, _campaign_task, _held_lease_id
    _ = app
    # Sovereign-strict must prove its egress guard before serving (fail-closed:
    # an unproven strict posture raises and the app refuses to start). The
    # result is cached in-process for GET /ops/posture.
    await asyncio.to_thread(verify_posture_or_raise)
    metrics.init_tracing("web")  # no-op unless tracing is enabled + endpoint set
    clear_demote_callbacks()
    register_demote_callback(_stop_probe_loop)
    bootstrap_ops_control_plane()

    if settings.ops_ha_active():
        logger.warning(
            "Ops CP HA enabled instance=%s etcd=%s",
            settings.ops_cp_instance_id,
            settings.ops_etcd_endpoints,
        )
        mark_standby()
        _campaign_task = asyncio.create_task(_campaign_loop())
    else:
        set_ha_disabled_role()
        logger.info("Ops CP HA disabled (single-writer mode)")
        if settings.ops_probe_enabled:
            _probe_task = asyncio.create_task(_ops_probe_loop())

    try:
        yield
    finally:
        if _campaign_task is not None:
            _campaign_task.cancel()
            try:
                await _campaign_task
            except asyncio.CancelledError:
                pass
            _campaign_task = None
        if _probe_task is not None:
            _probe_task.cancel()
            try:
                await _probe_task
            except asyncio.CancelledError:
                pass
            _probe_task = None
        if _held_lease_id is not None and settings.ops_ha_active():
            try:
                from app.ops.consensus import get_consensus_backend

                get_consensus_backend().resign(_held_lease_id)
            except Exception:
                logger.exception("failed to resign etcd lease on shutdown")
            _held_lease_id = None
        metrics.shutdown_tracing()


app = FastAPI(title="TESS Engine API", lifespan=lifespan)

# Observability is opt-in: when both toggles are off (default) nothing is mounted, so
# /health, /ws, and the product path are byte-for-byte unchanged.
if settings.ops_metrics_enabled or settings.ops_tracing_enabled:
    app.add_middleware(metrics.OpsObservabilityMiddleware)
    if settings.ops_metrics_enabled and metrics.prometheus_available():
        from starlette.responses import Response

        @app.get("/metrics")
        def _ops_metrics() -> Response:
            body, content_type = metrics.render_latest()
            return Response(content=body, media_type=content_type)

app.include_router(health_router)
app.include_router(ws_router)
app.include_router(ops_router)


@app.get("/")
async def read_root():
    return {"status": "TESS Engine is running and awaiting instructions."}
