"""s08 — Empty-blob restore / first persist and stale wrong-term writer."""

from __future__ import annotations

from .. import docker_util as dk
from .. import observables as obs
from ..harness import ScenarioContext

ID = "s08_empty_blob"
TITLE = "Empty-blob restore and stale writer reject"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id
    assert other_id

    # --- (a) blob absent, matching term: primary first persist recreates blob ---
    term = obs.redis_fence_term(cfg)
    obs.redis_del(cfg, obs.REDIS_BLOB_KEY)
    if obs.redis_blob(cfg) is not None:
        raise obs.AssertionError_("blob still present after DEL")

    code, body = obs.mutate_probe(topo.primary_base, token=cfg.admin_token)
    if not (200 <= code < 300):
        raise obs.AssertionError_(
            f"(a) primary first persist mutate failed status={code} body={body}"
        )

    def _blob_back():
        blob = obs.redis_blob(cfg)
        return blob if blob is not None else None

    blob = obs.wait_until(
        _blob_back,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="blob recreated after empty-blob persist",
    )
    if obs.redis_fence_term(cfg) != term and obs.redis_fence_term(cfg) < term:
        raise obs.AssertionError_("fence term decreased on empty-blob persist")
    _ = blob

    # --- (b) stale wrong-term writer cannot create/clobber blob ---
    active_before = obs.active_provider_id(cfg)
    blob_before = obs.redis_blob(cfg)
    term_now = obs.redis_fence_term(cfg)
    # Delete blob again and bump term so primary's cached term is stale.
    obs.redis_del(cfg, obs.REDIS_BLOB_KEY)
    obs.redis_set(cfg, obs.REDIS_FENCE_KEY, str(term_now + 7))

    code2, body2 = obs.mutate_set_active(
        topo.primary_base, other_id, token=cfg.admin_token
    )
    if 200 <= code2 < 300 and obs.active_provider_id(cfg) not in (active_before, None):
        if obs.active_provider_id(cfg) != active_before:
            raise obs.AssertionError_(
                f"(b) stale writer created wrong active status={code2} body={body2}"
            )

    # Restore blob from standby/new primary path via heal+wait, but first assert
    # active wasn't flipped if blob reappeared from stale writer.
    active_after = obs.active_provider_id(cfg)
    if active_after is not None and active_before is not None:
        if active_after != active_before:
            raise obs.AssertionError_(
                f"(b) active_provider_id changed by stale empty-blob writer: "
                f"{active_before} -> {active_after}"
            )

    # If a blob exists, it must not carry the wrong active id.
    blob_after = obs.redis_blob(cfg)
    if blob_after is not None and blob_before is not None:
        ba = (blob_after.get("routing") or {}).get("active_provider_id")
        bb = (blob_before.get("routing") or {}).get("active_provider_id")
        if ba != bb and ba != active_before:
            raise obs.AssertionError_(f"(b) blob clobber active {bb} -> {ba}")

    # Part (b) deliberately sets Redis fence ahead of etcd. promote_redis_fence
    # requires etcd_term > redis_term, so the cluster may not re-elect until the
    # next scenario's reset wipes Redis keys. Do not require single-primary here;
    # (a)/(b) artifact checks are the pass criteria. Heal containers only.
    dk.heal_all(cfg)
