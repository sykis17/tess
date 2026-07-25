# TESS Engine — Control-plane HA: Quorum Fence Store opener

**Lineage.** This continues the **control-plane HA hardening** line — `CP HA v1`
(etcd lease election + fence-term CAS, commit `84b81f5`) → Step 2 split-brain
harness ([CP_HA_S2_OPENER.md](CP_HA_S2_OPENER.md)) → Step 3 metrics/tracing →
Step 4 offline/sovereign packaging → Step 5 engineering report. It is **distinct
from the multi-cloud demo `Session N` track**; that track's Session 10 slot
remains *Shared Redis / seamless (Track C)*. Named descriptively
(`CP_HA_QUORUM`) rather than `CP_HA_S6` because this is a multi-step arc of its
own, and the flat "Step N" numbering already reached Step 5.

**Authoritative contract:** [deploy/MULTI_CLOUD.md](../../../deploy/MULTI_CLOUD.md)
§ Control-plane HA v1. **Invariants:** `CLAUDE.md` § "Ops control-plane HA —
critical invariants." Both must be kept green on every step here (split-brain
harness + `tests/test_ops_fencing.py` before each commit).

---

## Status

- **Step 1 — LANDED (this session).** `FenceStore` seam extracted in
  [app/ops/store.py](../../../app/ops/store.py): a `FenceStore` Protocol +
  `RedisFenceStore` + `get/set/reset_fence_store()` registry; the four durable
  functions (`promote_redis_fence`, `persist_store`, `restore_store`,
  `read_redis_fence_term`) are now thin wrappers that delegate the raw
  term/blob/CAS ops to the active store while keeping metrics and the
  restore→demote→raise severity handling in the wrapper. **Zero behavioral diff**
  — 271 unit tests green; split-brain harness `run-all` green.
- **Step 2 — LANDED.** `EtcdFenceStore` implemented in
  [app/ops/store.py](../../../app/ops/store.py), reusing the shared `etcd_post`
  gateway helper now extracted in
  [app/ops/consensus.py](../../../app/ops/consensus.py): `cas_persist` is a single
  VALUE-compare `txn`; `promote_term` is a read-then-CAS retry loop; a payload-size
  guard bounds the blob under etcd's ~1.5 MiB request limit. Promote is now
  idempotent (`<=`) in both backends (Redis Lua `<`→`<=` + `_FakeRedis` moved to
  [tests/fence_fakes.py](../../../tests/fence_fakes.py) and updated in the same
  change). A parameterized parity suite
  ([tests/test_fence_store_parity.py](../../../tests/test_fence_store_parity.py))
  runs one contract against both backends — **4/4 against a live etcd** (273 unit +
  parity green; harness re-verified 10/10). `EtcdFenceStore` is not yet wired into
  `persist_store` — that is Steps 4–5.
- **Steps 3–6 — pending**, one landing each (see Migration plan).

---

## Problem statement (corrected against the code)

The original draft framed Redis as *"the de facto coordinator … a single point of
failure for the exact property the system exists to protect."* Reading the code
shows that framing is out of date in a way that **narrows and sharpens** the work:

- **etcd is already the authoritative coordinator.**
  [app/ops/consensus.py](../../../app/ops/consensus.py) `EtcdHttpConsensus` is a
  thin httpx client against etcd's gRPC-JSON gateway (base64 keys, no native
  dep). It already runs leader election **and** mints a strictly-monotonic fence
  term at `/tess/ops/cp/fence_term` (`_increment_fence_term`). The "write a thin
  httpx etcd client" the draft proposed **already exists**.
- **Redis is not the coordinator.** It holds the durable control-plane blob
  (`ops:control_plane`) and a *mirrored* term (`ops:control_plane:fence_term`)
  used purely as a second CAS guard on durable writes. All of it is localized in
  `app/ops/store.py`.
- **The real gap** is the **durable write path**: `persist_store()`'s blob CAS
  (`_LUA_PERSIST_CAS`) is Redis-only. If Redis is down or fails over lossily,
  durable CP persistence and the second CAS gate are unavailable or unsafe. The
  project principle — *a single failure leaves two clear solutions available* —
  holds for leadership/term (etcd) but **not for durable persistence**.

**Target (confirmed):** make the fence-guarded **durable write linearizable
end-to-end** by moving the durable blob + its CAS guard into etcd, **reusing
`EtcdHttpConsensus`** rather than writing a second wire client. Side benefit: this
collapses the documented known limitation (*"after an external Redis fence bump
the cluster is unelectable"*) because term and CAS then live in one linearizable
store.

## Options considered (resolved, not re-litigated)

- **etcd (chosen)** — Raft-backed linearizable CAS via `txn` (value compare /
  `mod_revision`), TTL leases, one-node-failure tolerance with quorum. Already
  deployed for lease + term; extending it to the durable store keeps one
  coordinator. Redis Sentinel / `WAIT`, embedded Raft, and Postgres-on-DCS were
  weighed in the draft and rejected (no linearizable failover, or circular DCS
  dependency). No re-deliberation needed.
- **Client (chosen)** — reuse `EtcdHttpConsensus` (`_post` / `_b64` / txn).
  The draft's "write ~150 lines of httpx client" is **superseded**: that client
  exists and is exercised by the harness. Owning a second one would duplicate the
  wire helpers.

## Key design decisions (locked — includes cold-review corrections)

1. **`promote_term` is idempotent (`<=`), not strict (`<`).** In the etcd backend
   the election already writes the exact term to `/tess/ops/cp/fence_term` before
   the promotion path runs, so `stored == term` at promote time. Strict `<` would
   reject *every* promotion (and self-demote) and break Redis/etcd parity.
   Canonical semantics for both backends: succeed iff `stored <= term` (install
   when strictly less), reject iff `stored > term`. Redis aligns `<` → `<=` in
   Step 2 (one-char Lua change) with the `_FakeRedis` promote script updated in
   the same commit. **Step 1 kept the strict `<` verbatim** to preserve its
   zero-diff property.
2. **Keep our own integer term, not etcd revisions.** `mod_revision` is used only
   as the CAS guard, never exposed; `can_mutate` logic is untouched.
3. **Only the durable blob + CAS guard move.** Redis stays for caches, queues, and
   non-safety data. Small blast radius.
4. **Two flags at cutover**, not one: `ops_fence_shadow` (bool) +
   `ops_fence_authority` (`redis|etcd`). HA-off keeps the unconditional Redis SET
   single-writer path regardless.
5. **Harness observables/reset migrate to the authoritative backend** (etcd read
   helpers prepared in Step 3, switched in Step 5) so `assert_durable_unchanged`
   never goes vacuous at cutover.
6. **Shadow divergence is defined narrowly** — counted only when *both backends
   are reachable and their outcomes differ*. Shadow-unreachable is a separate
   `result` label value and never blocks the authoritative write, so "0 divergence
   across a full cycle" survives the etcd-down window in scenario `s06`.
7. **`EtcdFenceStore` asserts a payload-size bound** (etcd's ~1.5 MiB default
   request limit — distinct from compaction debt; the blob grows with providers).
8. **etcd stays on the 3.5.x line**, patch-pinned to current (3.5.32), bump
   riding Step 3. `docker-compose.offline.yml` stays **single-node** this arc (the
   3-node etcd is a harness verification overlay; multi-node-offline is deferred
   to the multi-cloud third-leg session, keeping the Sovereignty Audit
   unperturbed).
9. **Leases replace polling for soft-timeout — later, not here.** Parity on plain
   CAS first.

## The seam

`FenceStore` covers every durable call site (all external callers already go
through the module-level functions):

| Operation | Redis today | Semantics |
|---|---|---|
| `read_term() -> int` | `GET fence_term` | plain read |
| `promote_term(term) -> bool` | `_LUA_PROMOTE_FENCE` | idempotent monotonic install (`<=`; Redis is `<` until Step 2) |
| `cas_persist(term, payload) -> bool` | `_LUA_PERSIST_CAS` | write blob iff stored term `==` term, atomic |
| `write_blob(payload)` | `SET` | HA-off single-writer |
| `read_blob() -> str \| None` | `GET blob` | plain read |

Severity handling (restore + demote + raise `FenceCasError`) and metrics
(`record_cas` / `record_fence_reject`) live in the **wrappers**, so every backend
inherits identical semantics and the backend classes stay pure storage. Registry
mirrors `get_consensus_backend()`.

## Migration plan

1. **Extract the seam** — *DONE* (see Status).
2. **`EtcdFenceStore` + parity suite** — reuse `EtcdHttpConsensus` helpers;
   `cas_persist` = one etcd `txn` (compare term VALUE == → put blob); `promote_term`
   = read-then-`VALUE==`-CAS-with-retry (etcd VALUE compares are lexicographic, so
   `stored < term` is *not* a safe single `LESS` compare on decimal strings — mirror
   `_increment_fence_term`). Align Redis `<` → `<=` + `_FakeRedis` in the same
   commit. Parameterize the store tests over both backends; acceptance = identical
   accept/reject + restore/demote outcomes.
3. **3-node etcd in the harness** — `etcd-1/2/3`, comma-list endpoints (client
   tries in order), harness learns 3 members; add etcd artifact observables
   (`etcd_fence_term`/`etcd_blob`/…) and reset deletes the etcd blob key while the
   term persists and climbs monotonically (the `etcd_data` volume survives
   recreate — wiping it to 0 would mask monotonicity regressions). Acceptance:
   10/10 with a 3-member coordinator (durable store still Redis-authoritative
   here). Add the etcd ops runbook (automated compaction, defrag, snapshots).
4. **Shadow mode** — dual-write behind `ops_fence_shadow`; etcd shadows every CAS;
   `tess_ops_fence_shadow_divergence_total{op,result}` (allowlisted labels only).
   Acceptance: full harness cycle with divergence 0.
5. **Cutover** — `ops_fence_authority=etcd`; remove the dual-write path; switch
   harness observables to the authoritative backend; update MULTI_CLOUD.md +
   CLAUDE.md ("durable writes go through the fence" now = etcd txn-CAS); note
   boot-time `restore_store` now needs etcd reachable.
6. **The scenario Redis could never pass** — new `sNN_kill_etcd_leader_mid_storm`:
   kill the etcd leader during a mutation storm; assert zero fence violations,
   mutation continues on 2/3 quorum, terms strictly monotonic across failover.

## Invariants (unchanged, now stronger)

- Fence term strictly monotonic — now including across coordinator failover.
- `can_mutate` never simultaneously true on two nodes (harness-checked).
- `tests/test_ops_fencing.py`: worker keeps exactly 6 `check_fence_live`, no
  cached-role APIs; CAS reject == etcd reject severity. `tests/test_ops_metrics.py`:
  label allowlist. Split-brain harness runs on **every** step (each touches the
  CAS/consensus path).

## Risks and mitigations

- **Cross-cloud Raft latency** (future multi-provider): EU RTT well under etcd
  defaults; Raft uses no wall clocks, so cross-cloud skew is a non-safety issue.
- **etcd ops** (compaction/defrag/snapshots/fsync disks): runbook + automated
  compaction from Step 3; payload-size guard from Step 2.
- **Client bit-rot**: mitigated by owning the thin gateway client; JSON gateway is
  stable across 3.x.

## Out of scope

Multi-cloud third leg (etcd topology is designed for it but deployed
single-provider first), lease-based soft-timeout rework, product-graph
observability. Shared Redis / seamless (Track C) is the multi-cloud demo track's
concern, not this lineage.

## Verification — per-step gates

Run **all three** on every step that touches the store / consensus / CAS path
(all remaining steps do). The first two run on the host; the harness needs Docker.

1. **Unit + Redis parity:** `pytest tests/`. This passes with the **etcd contract
   tests skipped** — a plain green run does **not** exercise the etcd backend.
   "Green" ≠ "etcd-verified"; never conflate them (that is exactly how a parity
   suite rots the day after it is written).
2. **Live-etcd parity (required):** run a throwaway single-node etcd on a published
   port and point the parity suite at it:
   ```bash
   docker run -d --rm -p 12379:2379 --name tess-parity-etcd \
     -e ETCD_NAME=t -e ETCD_LISTEN_CLIENT_URLS=http://0.0.0.0:2379 \
     -e ETCD_ADVERTISE_CLIENT_URLS=http://127.0.0.1:2379 \
     -e ETCD_LISTEN_PEER_URLS=http://0.0.0.0:2380 \
     -e ETCD_INITIAL_ADVERTISE_PEER_URLS=http://127.0.0.1:2380 \
     -e ETCD_INITIAL_CLUSTER=t=http://127.0.0.1:2380 \
     -e ETCD_INITIAL_CLUSTER_STATE=new quay.io/coreos/etcd:v3.5.16
   OPS_TEST_ETCD_ENDPOINT=http://127.0.0.1:12379 pytest tests/test_fence_store_parity.py
   docker rm -f tess-parity-etcd
   ```
3. **Split-brain harness:** bring up base + ops-ha (+ ops-obs for `s10`), then
   `python -m scripts.ops_cp_splitbrain run-all` = 10/10. Two environment gotchas:
   the harness reads the admin token from `OPS_ADMIN_TOKEN` and must match the value
   the web container took from `.env` (compose interpolates `${OPS_ADMIN_TOKEN}`);
   and export `OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml` so `s10` can scrape
   `/metrics`.

## Baseline artifacts (do not regress)

- [app/ops/store.py](../../../app/ops/store.py) — the seam.
- [app/ops/consensus.py](../../../app/ops/consensus.py),
  [app/ops/fencing.py](../../../app/ops/fencing.py) — reuse targets; wrappers.
- [tests/test_ops_fencing.py](../../../tests/test_ops_fencing.py),
  [tests/test_ops_metrics.py](../../../tests/test_ops_metrics.py).
- [docker-compose.ops-ha.yml](../../../docker-compose.ops-ha.yml),
  [scripts/ops_cp_splitbrain/](../../../scripts/ops_cp_splitbrain/).
- [deploy/MULTI_CLOUD.md](../../../deploy/MULTI_CLOUD.md) § Control-plane HA v1.
