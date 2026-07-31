"""s08 — Empty-blob restore / first persist, and a stale wrong-term writer.

Part (a) is authority-agnostic once it reads the AUTHORITATIVE store: delete the durable
blob, mutate, and the primary's first persist recreates it.

Part (b) tests the stale wrong-term writer. Under Redis authority the bumped Redis term
strands the primary and the CAS reject keeps it from creating a wrong-active blob. Under
etcd authority the term store is unified, so the primary re-syncs at the bumped term (this
bug class is dissolved) — bump both term stores together to keep them symmetric (the etcd
bump drives re-sync; the Redis set is inert under etcd authority) and assert the surviving
invariant: no split-brain, monotonic term, no durable corruption.
"""

from __future__ import annotations

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
    term = obs.durable_fence_term(cfg)
    obs.durable_del_blob(cfg)
    if obs.durable_blob(cfg) is not None:
        raise obs.AssertionError_("durable blob still present after DEL")

    code, body = obs.mutate_probe(topo.primary_base, token=cfg.admin_token)
    if not (200 <= code < 300):
        raise obs.AssertionError_(
            f"(a) primary first persist mutate failed status={code} body={body}"
        )

    obs.wait_until(
        lambda: obs.durable_blob(cfg),
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="durable blob recreated after empty-blob persist",
    )
    if obs.durable_fence_term(cfg) < term:
        raise obs.AssertionError_("fence term decreased on empty-blob persist")

    # --- (b) stale wrong-term writer cannot clobber the durable active ---
    active_before = obs.durable_active_provider_id(cfg)
    blob_before = obs.durable_blob(cfg)
    term_now = obs.durable_fence_term(cfg)

    if cfg.fence_authority == "etcd":
        _run_b_etcd(ctx, active_before, term_now + 7)
    else:
        _run_b_redis(ctx, active_before, blob_before, term_now + 7)

    # Part (b) leaves the durable term ahead of nothing electable in some paths; the
    # (a)/(b) artifact checks are the pass criteria. Heal containers only.
    ctx.drv.heal_all()


def _run_b_redis(ctx, active_before, blob_before, bumped: int) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id

    # Delete blob again and bump term so the primary's cached term is stale.
    obs.redis_del(cfg, obs.REDIS_BLOB_KEY)
    obs.redis_set(cfg, obs.REDIS_FENCE_KEY, str(bumped))

    code2, body2 = obs.mutate_set_active(
        topo.primary_base, other_id, token=cfg.admin_token
    )
    if 200 <= code2 < 300 and obs.active_provider_id(cfg) not in (active_before, None):
        if obs.active_provider_id(cfg) != active_before:
            raise obs.AssertionError_(
                f"(b) stale writer created wrong active status={code2} body={body2}"
            )

    active_after = obs.active_provider_id(cfg)
    if active_after is not None and active_before is not None:
        if active_after != active_before:
            raise obs.AssertionError_(
                f"(b) active_provider_id changed by stale empty-blob writer: "
                f"{active_before} -> {active_after}"
            )

    blob_after = obs.redis_blob(cfg)
    if blob_after is not None and blob_before is not None:
        ba = (blob_after.get("routing") or {}).get("active_provider_id")
        bb = (blob_before.get("routing") or {}).get("active_provider_id")
        if ba != bb and ba != active_before:
            raise obs.AssertionError_(f"(b) blob clobber active {bb} -> {ba}")


def _run_b_etcd(ctx, active_before, bumped: int) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id

    # Unified term store: perturb etcd (authoritative); also set the Redis fence key so
    # both term stores stay symmetric. Under etcd authority the Redis set is inert (Redis
    # is caches + pub/sub post-cutover) — the etcd bump is what drives re-sync. The primary
    # re-syncs at the bumped term.
    obs.etcd_put_fence_term(cfg, bumped)
    obs.redis_set(cfg, obs.REDIS_FENCE_KEY, str(bumped))

    obs.mutate_set_active(topo.primary_base, other_id, token=cfg.admin_token)

    # Invariant: no split-brain, monotonic term, no durable corruption. (The stale-writer
    # "wrong blob" bug is dissolved; the mutate may reject-then-recover or succeed.)
    def _single_primary():
        try:
            n, a, b = obs.count_primaries(cfg)
        except Exception:
            return None
        return (a, b) if n == 1 else None

    obs.wait_until(
        _single_primary,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="single primary reconverges after empty-blob term perturbation",
    )
    now = obs.durable_fence_term(cfg)
    if now < bumped:
        raise obs.AssertionError_(
            f"etcd term lowered below external bump: bumped={bumped} now={now}"
        )
    active_after = obs.durable_active_provider_id(cfg)
    if active_after not in (active_before, other_id):
        raise obs.AssertionError_(
            f"durable active corrupted after term perturbation: {active_after!r} "
            f"not in {{{active_before!r}, {other_id!r}}}"
        )
