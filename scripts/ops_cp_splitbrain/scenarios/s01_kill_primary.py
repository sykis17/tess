"""s01 — Primary killed mid-idle (automate live smoke)."""

from __future__ import annotations

from .. import docker_util as dk
from .. import observables as obs
from ..harness import ScenarioContext

ID = "s01_kill_primary"
TITLE = "Primary killed mid-idle"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    old_term = topo.pre_fault_term
    primary_name = dk.container_name(cfg, topo.primary_service)
    standby_base = topo.standby_base
    old_primary_base = topo.primary_base

    fence_before = obs.redis_fence_term(cfg)
    active_before = obs.active_provider_id(cfg)
    blob_before = obs.redis_blob(cfg)

    dk.docker_stop(primary_name)

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
        label="standby promote after kill",
    )

    dk.docker_start(primary_name)

    def _revived_ok():
        try:
            revived = obs.ha(cfg, old_primary_base)
            other = obs.ha(cfg, standby_base)
        except Exception:
            return None
        roles = [revived.get("role"), other.get("role")]
        if roles.count("primary") > 1:
            return None
        # Accept: revived standby/demoted, or single primary after clean re-election.
        if roles.count("primary") == 1:
            return (revived, other)
        return None

    revived, other = obs.wait_until(
        _revived_ok,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="single primary after revive",
    )

    zombie_base = old_primary_base
    if revived.get("role") == "primary":
        # Revived won; zombie is the other node if standby, else skip zombie on winner.
        zombie_base = standby_base if other.get("role") != "primary" else old_primary_base
        if revived.get("instance_id") == promoted.get("instance_id"):
            # Same primary as promoted path — use old container only if standby.
            if revived.get("role") == "primary" and other.get("role") != "standby":
                pass

    # Prefer asserting against a non-primary node.
    a, b = obs.ha_both(cfg)
    for base, h in ((cfg.cp_a, a), (cfg.cp_b, b)):
        if h.get("role") != "primary":
            zombie_base = base
            break

    code_unauth, body_unauth = obs.mutate_probe(zombie_base, token=None)
    if code_unauth != 503:
        raise obs.AssertionError_(
            f"zombie unauthed mutate expected 503 got {code_unauth} body={body_unauth}"
        )
    code_auth, body_auth = obs.mutate_probe(zombie_base, token=cfg.admin_token)
    if code_auth != 503:
        raise obs.AssertionError_(
            f"zombie authed mutate expected 503 got {code_auth} body={body_auth}"
        )

    obs.assert_durable_unchanged(
        cfg,
        fence_before=max(fence_before, int(promoted.get("etcd_fence_term") or 0)),
        active_before=active_before,
        blob_before=blob_before,
    )
    # Term must have advanced from pre-fault.
    if obs.redis_fence_term(cfg) <= old_term:
        raise obs.AssertionError_("fence term did not advance after kill/promote")
