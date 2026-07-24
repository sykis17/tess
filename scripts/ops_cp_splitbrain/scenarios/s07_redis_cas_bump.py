"""s07 — Real Redis CAS reject (bump fence_term while primary holds stale term)."""

from __future__ import annotations

from .. import observables as obs
from ..harness import ScenarioContext

ID = "s07_redis_cas_bump"
TITLE = "Real-Redis CAS reject via fence_term bump"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id
    assert other_id

    t = obs.redis_fence_term(cfg)
    if t <= 0:
        raise obs.AssertionError_("expected redis fence_term > 0 before CAS bump")

    blob_before = obs.redis_blob(cfg)
    active_before = obs.active_provider_id(cfg)
    bumped = t + 5
    obs.redis_set(cfg, obs.REDIS_FENCE_KEY, str(bumped))

    code, body = obs.mutate_set_active(
        topo.primary_base, other_id, token=cfg.admin_token
    )

    # Must not succeed durable switch.
    if 200 <= code < 300 and obs.active_provider_id(cfg) != active_before:
        raise obs.AssertionError_(
            f"CAS bump mutate clobbered active status={code} body={body}"
        )
    if obs.active_provider_id(cfg) != active_before:
        raise obs.AssertionError_(
            f"active_provider_id changed after CAS bump mutate: "
            f"{active_before} -> {obs.active_provider_id(cfg)}"
        )

    # Primary should demote (redis_cas_rejected) within convergence.
    def _demoted():
        try:
            h = obs.ha(cfg, topo.primary_base)
        except Exception:
            return None
        if h.get("role") in ("demoted", "standby"):
            return h
        # After demote, peer may become primary — original may still briefly show primary
        # until campaign loop processes CAS demote.
        return None

    demoted = obs.wait_until(
        _demoted,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="primary demotes after redis CAS reject",
    )

    # Fence key must remain at bumped value (not clobbered downward by stale writer).
    fence_now = obs.redis_fence_term(cfg)
    if fence_now < bumped:
        raise obs.AssertionError_(
            f"stale writer lowered fence_term bumped={bumped} now={fence_now}"
        )

    blob_after = obs.redis_blob(cfg)
    if blob_before and blob_after:
        before_active = (blob_before.get("routing") or {}).get("active_provider_id")
        after_active = (blob_after.get("routing") or {}).get("active_provider_id")
        if before_active != after_active:
            raise obs.AssertionError_(
                f"blob active clobbered {before_active} -> {after_active}"
            )

    # Loud failure path preferred (503 fence_rejected) but demote+unchanged artifacts
    # are the authoritative pass criteria.
    if 200 <= code < 300:
        # HTTP success with unchanged artifacts still means we didn't get fence_rejected
        # body — acceptable only if demote happened (handler may have raced).
        if demoted.get("role") == "primary":
            raise obs.AssertionError_(
                f"mutate returned success and primary still primary status={code}"
            )
