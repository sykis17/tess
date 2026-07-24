"""s03 — Network partition primary ↔ etcd (full disconnect on single compose net)."""

from __future__ import annotations

from .. import docker_util as dk
from .. import observables as obs
from ..harness import ScenarioContext

ID = "s03_partition_primary_etcd"
TITLE = "Network partition primary <-> etcd"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    old_term = topo.pre_fault_term
    primary_name = dk.container_name(cfg, topo.primary_service)
    standby_base = topo.standby_base
    net = dk.default_compose_network(cfg, topo.primary_service)

    # Full disconnect isolates etcd (and Redis on single-network setups).
    dk.network_disconnect(net, primary_name)

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

    obs.wait_until(
        _promoted,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="standby promote after primary<->etcd partition",
    )

    dk.network_connect(net, primary_name)

    def _single():
        try:
            n, a, b = obs.count_primaries(cfg)
        except Exception:
            return None
        return (a, b) if n == 1 else None

    obs.wait_until(
        _single,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="single primary after partition heal",
    )
