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
- **Step 3 — LANDED.** The harness overlay ([docker-compose.ops-ha.yml](../../../docker-compose.ops-ha.yml))
  is now a **3-node etcd quorum** (etcd-1/2/3, 3.5.32, auto-compaction). The client
  fails over across all member URLs
  ([app/ops/consensus.py](../../../app/ops/consensus.py)::`etcd_post_failover`), so a
  single-node loss is transparent while a majority loss demotes. The harness is
  3-member-aware (config/heal/reset/baseline) and `s06` now stops **2 of 3** to
  reach genuine quorum loss; etcd-artifact observables
  (`etcd_fence_term`/`etcd_blob`/…) are prepared for the cutover.
  **Robustness fix the 3-node topology surfaced:** `GET /ops/ha` did a *blocking*
  synchronous `read_election()` on the async event loop; a reachable-but-quorum-less
  member made that read hang ~8–10s, so the endpoint could not report the (already
  correct) demotion within the harness window. `/ops/ha` now offloads the fresh read
  to a thread with a 2.5s bound and falls back to the cached role
  ([app/api/ops.py](../../../app/api/ops.py)). Verified: 273 unit + 4/4 live-etcd
  parity; **split-brain harness run-all 10/10 on the 3-node cluster**.
- **Step 4 — LANDED.** Shadow dual-write behind `ops_fence_shadow` (default off):
  after the authoritative Redis persist CAS, a **bounded** etcd shadow write compares
  outcomes and records `tess_ops_fence_shadow_total{op,outcome}` (outcome ∈
  match/diverge/unavailable — [app/ops/metrics.py](../../../app/ops/metrics.py)). The
  shadow uses `EtcdFenceStore` (single endpoint, 0.5s, **not** the failover ladder), so
  it can never pay the multi-endpoint retry cost on the authoritative path; it never
  raises and never changes the authoritative outcome
  ([app/ops/store.py](../../../app/ops/store.py)::`_shadow_compare_persist`). Verified:
  277 unit ([tests/test_fence_shadow.py](../../../tests/test_fence_shadow.py));
  divergence **0** against real etcd (28 matches across a shadow-on harness run + a
  dedicated mutation burst); split-brain harness run-all **10/10 with shadow on**.
- **Steps 5–6 — pending**, one landing each (see Migration plan).

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
8. **etcd stays on the 3.5.x line.** The harness overlay (`docker-compose.ops-ha.yml`)
   is pinned to current **3.5.32** and is now a **3-node quorum** (etcd-1/2/3).
   `docker-compose.offline.yml` stays **single-node at 3.5.16** — the version the
   Sovereignty Audit was verified against; aligning it to 3.5.32 is a deferred
   follow-up that requires re-running the offline egress harness, so the audit
   evidence is not edited to claim an unverified image. Multi-node-offline is
   deferred to the multi-cloud third-leg session.
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
4. **Shadow mode** — dual-write behind `ops_fence_shadow` (default off). After the
   authoritative Redis persist CAS returns, a **bounded** etcd shadow write runs and
   the outcomes are compared: `tess_ops_fence_shadow_total{op,outcome}` with
   `outcome ∈ {match, diverge, unavailable}` (allowlisted label names). *Bounded
   latency:* the shadow goes through `EtcdFenceStore` (single endpoint via `etcd_post`,
   **not** the failover ladder) with a 0.5s timeout — single attempt, so it can never
   pay the ~6s multi-endpoint retry cost on the authoritative path. Divergence (both
   reachable, outcomes differ) is the alarm and must stay 0; unreachable etcd is
   `unavailable`, never divergence; the shadow never raises. Only the persist CAS is
   shadowed — the fence term is already etcd-authoritative (minted by the election),
   so a promote shadow would be a trivial always-match. Acceptance: harness run-all
   green with shadow on **and** a divergence check reading 0.
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
     -e ETCD_INITIAL_CLUSTER_STATE=new quay.io/coreos/etcd:v3.5.32
   OPS_TEST_ETCD_ENDPOINT=http://127.0.0.1:12379 pytest tests/test_fence_store_parity.py
   docker rm -f tess-parity-etcd
   ```
3. **Split-brain harness:** bring up base + ops-ha (+ ops-obs for `s10`), then
   `python -m scripts.ops_cp_splitbrain run-all` = 10/10. Environment gotchas:
   the harness reads the admin token from `OPS_ADMIN_TOKEN` and must match the value
   the web container took from `.env` (compose interpolates `${OPS_ADMIN_TOKEN}`);
   export `OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml` so `s10` can scrape
   `/metrics`; and **to exercise shadow mode, set `OPS_FENCE_SHADOW=true` in the
   harness shell, not just the initial `up`** — `reset_stack` recreates the web
   containers via a `docker compose` subprocess, and `${OPS_FENCE_SHADOW:-false}`
   interpolates from *that* process's env, so a flag set only on the first `up`
   silently turns off after the first scenario.

## etcd operations (3-node cluster)

- **Compaction:** automated from day one — `ETCD_AUTO_COMPACTION_MODE=revision` +
  `ETCD_AUTO_COMPACTION_RETENTION=1000` on each member
  (`docker-compose.ops-ha.yml`). History stays bounded with no operator cron.
- **Defrag:** compaction frees logical space, not the file. Run
  `etcdctl defrag` one member at a time during a maintenance window if the DB file
  grows (it briefly blocks the member) — not automated.
- **Snapshots:** `etcdctl snapshot save` from any member; restore with
  `etcdctl snapshot restore`. After cutover the durable blob + term live in etcd, so
  a snapshot is the control-plane backup.
- **Quorum:** 3 members tolerate **one** loss transparently (client fails over).
  Losing **two** (scenario `s06`) makes the cluster unavailable — the primary
  demotes and mutations fail loudly, which is correct. Recover by restarting a
  member to regain majority.
- **Client failover:** web/worker pass all three client URLs via
  `OPS_ETCD_ENDPOINTS`; `EtcdHttpConsensus` tries them in order
  (`app/ops/consensus.py::etcd_post_failover`), so a single-node loss is transparent
  to election/keepalive.
- **Disks:** etcd needs fsync-capable storage; the named volumes
  (`etcd1_data`/`etcd2_data`/`etcd3_data`) satisfy this on the harness host.

## Baseline artifacts (do not regress)

- [app/ops/store.py](../../../app/ops/store.py) — the seam.
- [app/ops/consensus.py](../../../app/ops/consensus.py),
  [app/ops/fencing.py](../../../app/ops/fencing.py) — reuse targets; wrappers.
- [tests/test_ops_fencing.py](../../../tests/test_ops_fencing.py),
  [tests/test_ops_metrics.py](../../../tests/test_ops_metrics.py).
- [docker-compose.ops-ha.yml](../../../docker-compose.ops-ha.yml),
  [scripts/ops_cp_splitbrain/](../../../scripts/ops_cp_splitbrain/).
- [deploy/MULTI_CLOUD.md](../../../deploy/MULTI_CLOUD.md) § Control-plane HA v1.
