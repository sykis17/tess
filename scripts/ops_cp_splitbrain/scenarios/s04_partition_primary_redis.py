"""s04 — Primary loses Redis: pause Redis (portable) and assert no durable clobber.

Prefer pause over multi-network juggling on single-compose setups: disconnecting
the primary from the default network also cuts etcd. Pausing Redis isolates
durable CAS while etcd election remains reachable.
"""

from __future__ import annotations

import time

from .. import docker_util as dk
from .. import observables as obs
from ..harness import ScenarioContext

ID = "s04_partition_primary_redis"
TITLE = "Primary loses Redis (pause)"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id
    assert other_id

    redis_name = dk.container_name(cfg, cfg.redis_service)
    fence_before = obs.redis_fence_term(cfg)
    active_before = obs.active_provider_id(cfg)

    dk.docker_pause(redis_name)
    try:
        # Mutate while Redis is frozen — must not silently succeed a durable switch.
        # HTTP may hang briefly; urllib timeout returns status 0.
        code, body = obs.mutate_set_active(
            topo.primary_base, other_id, token=cfg.admin_token
        )
        if 200 <= code < 300:
            raise obs.AssertionError_(
                f"primary mutate succeeded while Redis paused status={code} body={body}"
            )
    finally:
        dk.docker_unpause(redis_name)

    # Give Redis a moment after unpause before reading keys.
    time.sleep(1.0)

    if obs.active_provider_id(cfg) != active_before:
        raise obs.AssertionError_(
            f"active_provider_id changed while Redis was paused: "
            f"{active_before} -> {obs.active_provider_id(cfg)}"
        )

    # Primary may demote on persist failure; either way, converge to one primary.
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
        label="single primary after Redis pause heal",
    )

    if obs.redis_fence_term(cfg) < fence_before:
        raise obs.AssertionError_("fence term decreased after Redis pause heal")
