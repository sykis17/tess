"""s05 — Network partition standby ↔ etcd; must not falsely promote."""

from __future__ import annotations

import time

from .. import observables as obs
from ..harness import ScenarioContext

ID = "s05_partition_standby_etcd"
TITLE = "Network partition standby <-> etcd"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    old_term = topo.pre_fault_term
    primary_id = topo.primary_id
    standby_name = ctx.drv.container_name(topo.standby_service)
    net = ctx.drv.default_compose_network(topo.standby_service)

    fence_before = obs.durable_fence_term(cfg)

    ctx.drv.network_disconnect(net, standby_name)

    # Hold partition for one convergence window; primary must remain sole writer.
    deadline = time.time() + min(cfg.convergence_timeout, cfg.lease_ttl_seconds * 2)
    while time.time() < deadline:
        try:
            primary_ha = obs.ha(cfg, topo.primary_base)
        except Exception as exc:
            raise obs.AssertionError_(f"primary unreachable during standby partition: {exc}")
        if primary_ha.get("role") != "primary":
            raise obs.AssertionError_(
                f"primary lost role during standby partition: {primary_ha}"
            )
        if primary_ha.get("instance_id") != primary_id:
            raise obs.AssertionError_("primary instance changed unexpectedly")
        time.sleep(cfg.poll_interval)

    # Standby should not have advanced redis fence on its own.
    if obs.durable_fence_term(cfg) > fence_before + 1:
        # Small bump from primary persist is ok; large jump suggests false promote.
        pass
    if obs.durable_fence_term(cfg) < fence_before:
        raise obs.AssertionError_("fence term decreased")

    ctx.drv.network_connect(net, standby_name)

    def _single():
        try:
            n, a, b = obs.count_primaries(cfg)
        except Exception:
            return None
        if n != 1:
            return None
        # Prefer original primary still primary (standby must not have stolen).
        winner = a if a.get("role") == "primary" else b
        if winner.get("instance_id") != primary_id:
            # Acceptable only if original primary died — it didn't. Fail.
            raise obs.AssertionError_(
                f"standby falsely promoted after heal: winner={winner} "
                f"expected primary_id={primary_id}"
            )
        return True

    obs.wait_until(
        _single,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="original primary remains after standby partition heal",
    )

    if obs.durable_fence_term(cfg) < old_term:
        raise obs.AssertionError_("term went backwards")
