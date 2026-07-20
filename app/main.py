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
from app.ops.bootstrap import bootstrap_ops_control_plane
from app.ops.failover import evaluate_failover
from app.ops.prober import probe_all_providers

logger = logging.getLogger(__name__)


async def _ops_probe_loop() -> None:
    """Background health probes + failover evaluation."""
    interval = max(5.0, settings.ops_probe_interval_seconds)
    while True:
        try:
            snapshots = await probe_all_providers()
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
        except Exception:
            logger.exception("Ops probe loop error")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_ops_control_plane()
    probe_task: asyncio.Task[None] | None = None
    if settings.ops_probe_enabled:
        probe_task = asyncio.create_task(_ops_probe_loop())
    try:
        yield
    finally:
        if probe_task is not None:
            probe_task.cancel()
            try:
                await probe_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="TESS Engine API", lifespan=lifespan)
app.include_router(health_router)
app.include_router(ws_router)
app.include_router(ops_router)


@app.get("/")
async def read_root():
    return {"status": "TESS Engine is running and awaiting instructions."}
