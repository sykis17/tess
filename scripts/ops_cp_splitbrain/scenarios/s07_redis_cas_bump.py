"""s07 — Stale-term writer under an external fence-term bump.

Redis authority: the CAS guard (Redis term) and the election term (etcd) are *separate*
stores, so bumping the Redis term strands the sitting primary at a stale term — its
persist CAS-rejects and it demotes (the classic split-brain guard).

Etcd authority (post-cutover): the term store is *unified* — the CAS guard IS the
election term. Bumping it advances the election too, so the sitting primary re-syncs at
the higher term within a campaign tick and durable writes resume. That dissolves this
bug class, so the etcd branch asserts the invariant that survives the dissolution: no
split-brain, a monotonic term (never lowered by a stale writer), and no durable
corruption — the mutate may reject-then-recover OR succeed post-resync, both are fine.
"""

from __future__ import annotations

from .. import observables as obs
from ..harness import ScenarioContext

ID = "s07_redis_cas_bump"
TITLE = "Stale-term writer under external fence-term bump"


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id
    assert other_id

    t = obs.durable_fence_term(cfg)
    if t <= 0:
        raise obs.AssertionError_(
            f"expected durable[{cfg.fence_authority}] fence_term > 0 before bump"
        )

    blob_before = obs.durable_blob(cfg)
    active_before = obs.durable_active_provider_id(cfg)
    bumped = t + 5

    if cfg.fence_authority == "etcd":
        _run_etcd(ctx, active_before, blob_before, bumped)
    else:
        _run_redis(ctx, active_before, blob_before, bumped)


def _run_redis(
    ctx: ScenarioContext,
    active_before: str | None,
    blob_before: dict | None,
    bumped: int,
) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id

    obs.redis_set(cfg, obs.REDIS_FENCE_KEY, str(bumped))

    code, body = obs.mutate_set_active(
        topo.primary_base, other_id, token=cfg.admin_token
    )

    # Must not succeed a durable switch.
    if obs.active_provider_id(cfg) != active_before:
        raise obs.AssertionError_(
            f"active_provider_id changed after CAS bump mutate: "
            f"{active_before} -> {obs.active_provider_id(cfg)}"
        )

    # Separate stores => the mismatch is persistent => sustained demote.
    def _demoted():
        try:
            h = obs.ha(cfg, topo.primary_base)
        except Exception:
            return None
        return h if h.get("role") in ("demoted", "standby") else None

    demoted = obs.wait_until(
        _demoted,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="primary demotes after redis CAS reject",
    )

    if obs.redis_fence_term(cfg) < bumped:
        raise obs.AssertionError_(
            f"stale writer lowered fence_term bumped={bumped} now={obs.redis_fence_term(cfg)}"
        )

    _assert_blob_active_unchanged(cfg, blob_before)

    if 200 <= code < 300 and demoted.get("role") == "primary":
        raise obs.AssertionError_(
            f"mutate returned success and primary still primary status={code}"
        )


def _run_etcd(
    ctx: ScenarioContext,
    active_before: str | None,
    blob_before: dict | None,
    bumped: int,
) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    other_id = ctx.other_provider_id

    # Perturb BOTH the etcd term (authoritative) and the Redis shadow term to the same
    # higher value. Bumping only one makes the authoritative reject while the shadow
    # accepts -> a false "diverge" that breaks the reverse-shadow soak's divergence==0
    # gate. After this the sitting primary's cached term is stale (for one campaign tick).
    obs.etcd_put_fence_term(cfg, bumped)
    obs.redis_set(cfg, obs.REDIS_FENCE_KEY, str(bumped))

    # May reject-then-recover (cached term still stale) OR succeed (campaign already
    # re-synced to the bumped term). Both are correct post-cutover; the race is ~1 tick.
    obs.mutate_set_active(topo.primary_base, other_id, token=cfg.admin_token)

    # Invariant 1: no split-brain — the cluster reconverges to exactly one primary.
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
        label="single primary reconverges after etcd term perturbation",
    )

    # Invariant 2: term monotonic — a stale writer never lowered the authoritative term.
    now = obs.durable_fence_term(cfg)
    if now < bumped:
        raise obs.AssertionError_(
            f"etcd term lowered below external bump: bumped={bumped} now={now}"
        )

    # Invariant 3: no durable corruption — the durable active is one of the two known
    # providers (either the incumbent or a legitimate switch to other_id), never garbage.
    active_after = obs.durable_active_provider_id(cfg)
    if active_after not in (active_before, other_id):
        raise obs.AssertionError_(
            f"durable active corrupted after term perturbation: {active_after!r} "
            f"not in {{{active_before!r}, {other_id!r}}}"
        )


def _assert_blob_active_unchanged(cfg, blob_before) -> None:
    blob_after = obs.durable_blob(cfg)
    if blob_before and blob_after:
        before_active = (blob_before.get("routing") or {}).get("active_provider_id")
        after_active = (blob_after.get("routing") or {}).get("active_provider_id")
        if before_active != after_active:
            raise obs.AssertionError_(
                f"blob active clobbered {before_active} -> {after_active}"
            )
