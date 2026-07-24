"""s06 — etcd down: sitting primary must demote after lease TTL; neither durable writer."""

from __future__ import annotations

from .. import docker_util as dk
from .. import observables as obs
from ..harness import ScenarioContext

ID = "s06_etcd_down"
TITLE = "etcd down - sitting primary demotes"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    primary_base = topo.primary_base
    primary_id = topo.primary_id
    etcd_name = dk.container_name(cfg, cfg.etcd_service)

    dk.docker_stop(etcd_name)

    def _primary_demoted():
        try:
            h = obs.ha(cfg, primary_base)
        except Exception:
            return None
        role = h.get("role")
        # Locked contract: must not remain primary on dead etcd past TTL.
        if role == "primary":
            return None
        if role in ("demoted", "standby"):
            return h
        # ha_disabled unexpected while HA configured
        return h if role != "primary" else None

    demoted = obs.wait_until(
        _primary_demoted,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="sitting primary demotes after etcd down",
    )
    if demoted.get("role") == "primary":
        raise obs.AssertionError_(
            f"sitting primary still primary with etcd down: {demoted}"
        )

    # Neither node claims durable primary writer.
    def _no_primary_writer():
        try:
            a, b = obs.ha_both(cfg)
        except Exception:
            return None
        roles = [a.get("role"), b.get("role")]
        if "primary" in roles:
            return None
        return (a, b)

    a, b = obs.wait_until(
        _no_primary_writer,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="neither node primary while etcd down",
    )

    # Mutates fail loudly on former primary.
    code, body = obs.mutate_probe(primary_base, token=cfg.admin_token)
    if 200 <= code < 300:
        raise obs.AssertionError_(
            f"mutate succeeded with etcd down status={code} body={body}"
        )
    if code not in (503, 500, 502) and not obs.is_fence_reject_response(code, body):
        raise obs.AssertionError_(
            f"mutate did not fail loudly with etcd down status={code} body={body}"
        )

    dk.docker_start(etcd_name)

    def _relected():
        try:
            n, aa, bb = obs.count_primaries(cfg)
        except Exception:
            return None
        return (aa, bb) if n == 1 else None

    obs.wait_until(
        _relected,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="single primary after etcd restore",
    )
    _ = primary_id
    _ = a
    _ = b
