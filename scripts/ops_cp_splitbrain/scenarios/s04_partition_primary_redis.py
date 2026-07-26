"""s04 — Primary loses Redis (pause Redis; portable, isolates the durable path).

Redis authority: the durable CAS lives in Redis, so a Redis outage must block the
durable switch — the mutate must NOT silently succeed, and the durable state must not
change.

Etcd authority (post-cutover): Redis is caches + pub/sub + shadow; the durable write is
the etcd txn-CAS. A Redis outage must NOT block a durable write — this is the arc's
headline capability. So the etcd branch is a POSITIVE test: the switch lands in etcd
while Redis is paused (the best-effort provider_changed publish is swallowed).

Pausing Redis (vs multi-network juggling) keeps etcd reachable so the election is
unaffected and only the Redis-backed path is exercised.
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
    fence_before = obs.durable_fence_term(cfg)
    active_before = obs.durable_active_provider_id(cfg)

    if cfg.fence_authority == "etcd":
        _run_etcd(ctx, redis_name, fence_before, active_before)
    else:
        _run_redis(ctx, redis_name, fence_before, active_before)


def _run_redis(ctx, redis_name, fence_before, active_before) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id

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

    _converge_single_primary(cfg, "single primary after Redis pause heal")

    if obs.redis_fence_term(cfg) < fence_before:
        raise obs.AssertionError_("fence term decreased after Redis pause heal")


def _run_etcd(ctx, redis_name, fence_before, active_before) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id

    dk.docker_pause(redis_name)
    try:
        # Durable authority is etcd; Redis loss must not block the durable switch.
        code, body = obs.mutate_set_active(
            topo.primary_base, other_id, token=cfg.admin_token
        )
        if not (200 <= code < 300):
            raise obs.AssertionError_(
                f"durable switch did not survive Redis loss under etcd authority "
                f"status={code} body={body}"
            )
        # The switch must be visible in the AUTHORITATIVE (etcd) durable store while
        # Redis is still paused — proving the write did not depend on Redis.
        etcd_active = obs.etcd_active_provider_id(cfg)
        if etcd_active != other_id:
            raise obs.AssertionError_(
                f"etcd durable active did not update while Redis paused: "
                f"{etcd_active!r} != {other_id!r}"
            )
    finally:
        dk.docker_unpause(redis_name)

    time.sleep(1.0)
    _converge_single_primary(cfg, "single primary after Redis pause heal (etcd authority)")

    if obs.etcd_fence_term(cfg) < fence_before:
        raise obs.AssertionError_("etcd fence term decreased after Redis pause heal")


def _converge_single_primary(cfg, label: str) -> None:
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
        label=label,
    )
