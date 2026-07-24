"""s09 — Zombie write with second provider (non-no-op active switch attempt)."""

from __future__ import annotations

from .. import docker_util as dk
from .. import observables as obs
from ..harness import ScenarioContext

ID = "s09_zombie_second_provider"
TITLE = "Zombie write with second dummy provider"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id
    active_before = ctx.active_provider_id
    assert other_id and active_before
    if other_id == active_before:
        raise obs.AssertionError_("other provider must differ from active")

    old_term = topo.pre_fault_term
    primary_name = dk.container_name(cfg, topo.primary_service)
    standby_base = topo.standby_base
    old_primary_base = topo.primary_base

    dk.docker_stop(primary_name)

    def _promoted():
        try:
            h = obs.ha(cfg, standby_base)
        except Exception:
            return None
        if h.get("role") != "primary":
            return None
        new_term = int(h.get("etcd_fence_term") or h.get("fence_term") or 0)
        return h if new_term > old_term else None

    obs.wait_until(
        _promoted,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="standby promote for zombie test",
    )

    dk.docker_start(primary_name)

    def _zombie_ready():
        try:
            revived = obs.ha(cfg, old_primary_base)
            other = obs.ha(cfg, standby_base)
        except Exception:
            return None
        if revived.get("role") == "primary" and other.get("role") == "primary":
            return None
        # Prefer old primary as zombie (non-primary).
        if revived.get("role") != "primary":
            return revived
        # If revived won election, use the other as zombie target instead.
        if other.get("role") != "primary":
            return {"_zombie_base": standby_base, **other}
        return None

    zombie_ha = obs.wait_until(
        _zombie_ready,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="zombie node non-primary",
    )
    zombie_base = zombie_ha.get("_zombie_base") or old_primary_base

    fence_before = obs.redis_fence_term(cfg)
    blob_before = obs.redis_blob(cfg)
    active_snap = obs.active_provider_id(cfg) or active_before

    # Unauthed — must be 503 fence body (fence-before-auth), not 401.
    code_u, body_u = obs.mutate_set_active(zombie_base, other_id, token=None)
    if code_u != 503:
        raise obs.AssertionError_(
            f"unauthed zombie set_active expected 503 got {code_u} body={body_u}"
        )
    detail_u = obs.detail_from_body(body_u)
    if detail_u.get("error") and detail_u.get("error") not in (
        "not_primary",
        "fence_rejected",
    ):
        # Still OK if role present
        if "role" not in detail_u:
            raise obs.AssertionError_(f"unauthed 503 missing fence detail: {body_u}")

    # Authed — 503 fence body.
    code_a, body_a = obs.mutate_set_active(
        zombie_base, other_id, token=cfg.admin_token
    )
    if code_a != 503:
        raise obs.AssertionError_(
            f"authed zombie set_active expected 503 got {code_a} body={body_a}"
        )

    obs.assert_durable_unchanged(
        cfg,
        fence_before=fence_before,
        active_before=active_snap,
        blob_before=blob_before,
    )

    # Pub/sub: no provider_changed from rejected zombie switch.
    (code3, body3), msg_count = obs.peek_provider_changed(
        cfg,
        lambda: obs.mutate_set_active(
            zombie_base, other_id, token=cfg.admin_token
        ),
        listen_seconds=2.0,
    )
    if code3 != 503:
        raise obs.AssertionError_(
            f"repeat zombie mutate expected 503 got {code3} body={body3}"
        )
    if msg_count > 0:
        raise obs.AssertionError_(
            f"provider_changed published on zombie reject count={msg_count}"
        )
