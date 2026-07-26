"""s02 — Primary paused (frozen process / stale lease). Artifacts > status codes."""

from __future__ import annotations

import time

from .. import docker_util as dk
from .. import observables as obs
from ..harness import ScenarioContext

ID = "s02_pause_primary"
TITLE = "Primary paused (frozen lease)"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    old_term = topo.pre_fault_term
    primary_name = dk.container_name(cfg, topo.primary_service)
    frozen_base = topo.primary_base
    standby_base = topo.standby_base
    other_id = ctx.other_provider_id
    assert other_id

    fence_before_pause = obs.durable_fence_term(cfg)
    active_before = obs.durable_active_provider_id(cfg)

    dk.docker_pause(primary_name)

    def _promoted():
        try:
            h = obs.ha(cfg, standby_base)
        except Exception:
            return None
        if h.get("role") != "primary":
            return None
        new_term = int(h.get("etcd_fence_term") or h.get("fence_term") or 0)
        if new_term <= old_term:
            return None
        return h

    promoted = obs.wait_until(
        _promoted,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="standby promote while primary paused",
    )

    fence_after_promote = obs.durable_fence_term(cfg)
    blob_after_promote = obs.durable_blob(cfg)
    active_after_promote = obs.durable_active_provider_id(cfg)

    # Strongest assert: mutate immediately after unpause — may still have cached
    # primary role, so status may be 503 OR fence-error 5xx; artifacts must not move.
    dk.docker_unpause(primary_name)
    time.sleep(0.05)  # fire in the stale-cache window

    code, body = obs.mutate_set_active(
        frozen_base, other_id, token=cfg.admin_token
    )
    if not obs.is_fence_reject_response(code, body):
        # Success (2xx) is a hard fail — durable write from zombie.
        if 200 <= code < 300:
            raise obs.AssertionError_(
                f"post-unpause mutate SUCCEEDED (must fail loudly) "
                f"status={code} body={body}"
            )
        raise obs.AssertionError_(
            f"post-unpause mutate did not fail loudly status={code} body={body}"
        )

    obs.assert_durable_unchanged(
        cfg,
        fence_before=fence_after_promote,
        active_before=active_after_promote,
        blob_before=blob_after_promote,
    )

    # No dual primary within convergence window.
    def _single():
        try:
            n, a, b = obs.count_primaries(cfg)
        except Exception:
            return None
        if n == 1:
            return (a, b)
        return None

    obs.wait_until(
        _single,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="single primary after unpause",
    )

    if fence_after_promote <= old_term or fence_after_promote < fence_before_pause:
        raise obs.AssertionError_(
            f"term did not advance on pause promote "
            f"old={old_term} before={fence_before_pause} after={fence_after_promote}"
        )
    if active_before != active_after_promote:
        # Promote alone shouldn't switch provider.
        raise obs.AssertionError_(
            f"active changed during pause promote {active_before} -> {active_after_promote}"
        )
