"""s11 — Kill the etcd RAFT leader mid-mutation-storm; durable writes must resume.

The harshest workload in the suite. A burst of durable mutations runs while the etcd Raft
leader is killed: quorum is retained (2/3), but a re-election gap opens in which no
authoritative write can land anywhere.

Acceptance is **bounded RESUME, not zero in-gap errors.** In-gap mutations may fail loudly
(fence-reject / 5xx) or block-and-succeed; what must hold is that durable writes resume on
the new leader within a bounded window, with:
- **zero silent losses** — a 2xx means the etcd txn-CAS committed, so success == durable;
- **zero fence violations** — never two CP primaries, and the durable active is never garbage;
- **a monotonic term** across the failover (never goes backwards).

Reverse-shadow soak evidence (etcd authority): the fault hits etcd; the shadow store is
Redis, which the kill does not touch — so every shadow write during the storm should be
`match`, with no `unavailable` noise. The assertion is not just `diverge == 0` but that the
`match` count **advanced** during the storm (non-vacuous: a silent no-op cannot pass).
"""

from __future__ import annotations

import time

from .. import docker_util as dk
from .. import observables as obs
from ..harness import ScenarioContext

ID = "s11_kill_etcd_leader_storm"
TITLE = "Kill etcd leader mid-mutation-storm; durable writes resume"

_PRE_KILL_MUTATIONS = 4


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    other_id = ctx.other_provider_id
    active_id = ctx.active_provider_id
    assert other_id and active_id and other_id != active_id

    targets = [active_id, other_id]
    term_before = obs.durable_fence_term(cfg)

    # --- Baseline burst: successful mutations establish the pre-storm shadow match count.
    for i in range(_PRE_KILL_MUTATIONS):
        _storm_once(ctx, targets[i % 2])
    shadow_before = obs.shadow_totals(cfg)
    if cfg.fence_authority == "etcd" and shadow_before["match"] <= 0:
        raise obs.AssertionError_(
            "s11 needs the observability overlay (OPS_METRICS_ENABLED): no shadow match "
            f"metric before the storm; totals={shadow_before}. Export OPS_HA_COMPOSE_OBS."
        )

    # --- Identify + kill the etcd RAFT leader (distinct from the CP primary).
    leader_svc = obs.etcd_leader_service(cfg)
    if leader_svc is None:
        raise obs.AssertionError_("could not identify etcd raft leader before storm")
    leader_name = dk.container_name(cfg, leader_svc)
    raft_before = obs.etcd_raft_term(cfg)
    # SIGKILL, not stop: SIGTERM lets etcd hand off leadership (near-zero gap, vacuous).
    # An ungraceful kill forces the survivors to ride out the election timeout — the real gap.
    dk.docker_kill(leader_name)

    # --- Storm through the re-election gap: keep firing until a durable write RESUMES.
    resumed = False
    codes: list[int] = []
    deadline = time.time() + cfg.convergence_timeout
    i = 0
    try:
        while time.time() < deadline:
            code = _storm_once(ctx, targets[i % 2])
            codes.append(code)
            i += 1
            # No split-brain at any point (sampled; /ops/ha is slow during the gap).
            if i % 4 == 0:
                _assert_no_split_brain(cfg)
            if 200 <= code < 300:
                resumed = True
                break
            # Any non-2xx here is a loud failure (503 fence / 5xx / 0 timeout) — acceptable
            # in-gap. The scenario only requires a durable write to eventually succeed.
        if not resumed:
            raise obs.AssertionError_(
                f"durable writes did not resume within {cfg.convergence_timeout}s after "
                f"killing etcd leader {leader_svc}; codes={codes}"
            )
    finally:
        dk.docker_start(leader_name)

    # --- Heal: whole etcd cluster back, single CP primary.
    obs.wait_until(
        lambda: obs.etcd_leader_service(cfg),
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="etcd leader present again after restart",
    )
    _wait_single_primary(cfg)
    _assert_no_split_brain(cfg)

    # --- Non-vacuity: the kill genuinely forced an etcd re-election (Raft term advanced),
    # so the storm rode through a real gap rather than a seamless graceful hand-off. Without
    # this, a SIGTERM-style leadership transfer would let s11 pass while testing nothing.
    raft_after = obs.etcd_raft_term(cfg)
    if raft_after <= raft_before:
        raise obs.AssertionError_(
            f"etcd raft term did not advance across leader kill ({raft_before} -> "
            f"{raft_after}) — no real re-election, so the gap was never exercised"
        )

    # --- Monotonic term across the failover.
    term_after = obs.durable_fence_term(cfg)
    if term_after < term_before:
        raise obs.AssertionError_(
            f"etcd term went backwards across leader failover {term_before} -> {term_after}"
        )

    # --- No durable corruption: active is one of the two known providers.
    active_after = obs.durable_active_provider_id(cfg)
    if active_after not in (active_id, other_id):
        raise obs.AssertionError_(
            f"durable active corrupted by leader-kill storm: {active_after!r}"
        )

    # --- Reverse-shadow soak evidence (etcd authority): diverge 0 AND match advanced.
    # The fault hit etcd; the shadow (Redis) was untouched, so every storm shadow write is a
    # real comparison — divergence here would be pure signal, and match must have advanced.
    if cfg.fence_authority == "etcd":
        shadow_after = obs.shadow_totals(cfg)
        if shadow_after["diverge"] > 0:
            raise obs.AssertionError_(
                f"reverse-shadow DIVERGED during leader-kill storm: {shadow_after}"
            )
        if shadow_after["match"] <= shadow_before["match"]:
            raise obs.AssertionError_(
                f"shadow match did not advance during storm (vacuous check): "
                f"before={shadow_before['match']} after={shadow_after['match']}"
            )


def _storm_once(ctx: ScenarioContext, target_id: str) -> int:
    """Fire set_active at both CP nodes; return 2xx if either accepted, else the last status.

    Firing at both avoids a slow /ops/ha primary-discovery round-trip each iteration (which
    stalls during the gap): the standby refuses fast (503 gate), and after failover whichever
    node is primary accepts. Success on either node means durable writes have resumed.
    """
    cfg = ctx.cfg
    last = 0
    for base in (ctx.topo.primary_base, ctx.topo.standby_base):
        code, _ = obs.mutate_set_active(base, target_id, token=cfg.admin_token)
        if 200 <= code < 300:
            return code
        last = code or last
    return last


def _assert_no_split_brain(cfg) -> None:
    try:
        n, a, b = obs.count_primaries(cfg)
    except Exception:
        return  # transient unreachable during the gap is not a violation
    if n > 1:
        raise obs.AssertionError_(f"split-brain during leader-kill storm: a={a} b={b}")


def _wait_single_primary(cfg) -> None:
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
        label="single primary after leader-kill heal",
    )
