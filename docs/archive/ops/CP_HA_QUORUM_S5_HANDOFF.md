# CP-HA Quorum Fence Store — Step 5 hand-off (resume here)

Hand-off for a fresh session to continue the **Quorum Fence Store** arc mid-Step-5.
Read the arc opener first: [CP_HA_QUORUM_OPENER.md](CP_HA_QUORUM_OPENER.md) (problem
framing, all fork resolutions, per-step verification gates, the etcd ops runbook).
This doc is the delta: exact git state, the uncommitted WIP, and the ordered
remaining work with enough detail to finish (or reconstruct) it.

---

## TL;DR — resume in 4 moves

1. `git status` should show **uncommitted** `app/core/config.py`, `app/ops/store.py`,
   `tests/conftest.py` (Step 5a store core). `python -m pytest tests/ -q` → **277 passed,
   2 skipped**. If the WIP is missing, reconstruct it from §"Step 5a — done" below.
2. Do the **ops.py mutation-lock + offload** (§"Immediate next task"). This is the
   sharpest piece — it prevents a real lost-update race the offload would otherwise
   introduce.
3. Add tests, flip harness observables + reframe `s04`/`s07`, update the contract docs.
4. **Soak gate then commit 5a**; then **5b** (remove dual-write). Gates + env gotchas in
   §"Verification".

Do **not** commit partial 5a — the arc keeps one harness-verified commit per step. The
WIP persists on disk; finish 5a, run the full gate, commit once.

---

## Git state (verified at hand-off)

- Branch: `cursor/cp-ha-quorum-fence-store` (tracks `origin/…`).
- Commits (all pushed): `6331b00` step 1 · `315b044` step 2 · `3a3444a` step 3 ·
  `3e72fbe` step 4.
- **PR #10** — title "…(steps 1-4)", body current through step 4.
- Uncommitted WIP in the working tree: `app/core/config.py`, `app/ops/store.py`,
  `tests/conftest.py` (Step 5a store core; 277 unit pass; behavior-preserving because
  default `ops_fence_authority="redis"` = the step-4 behavior).

To update PR #10 after 5a/5b: `gh` is at `C:\Program Files\GitHub CLI\gh.exe` (not on
PATH); `gh pr edit 10 --title … --body-file …`.

---

## The arc (context)

etcd is already the authoritative coordinator (election + monotonic term
`/tess/ops/cp/fence_term`, thin httpx gRPC-JSON client `app/ops/consensus.py`). Redis
holds the durable CP blob + a mirrored CAS-guard term. The arc moves the durable
blob + CAS into etcd so the fence-guarded durable write is linearizable, dissolving the
"external Redis bump → unelectable" limitation.

- **Step 1** (`6331b00`) FenceStore seam. **Step 2** (`315b044`) EtcdFenceStore + parity.
  **Step 3** (`3a3444a`) 3-node etcd quorum + failover client + `/ops/ha` event-loop-stall
  fix. **Step 4** (`3e72fbe`) shadow dual-write (`ops_fence_shadow`, default off), bounded.
- **Step 5 (in progress) = cutover.** Two commits: **5a** flip authority to etcd + keep a
  reverse-shadow soak; **5b** remove the dual-write after the soak shows 0 divergence.
- **Step 6** (future) kill-etcd-leader-mid-mutation-storm scenario.

---

## Step 5 design (SIGNED OFF — do not re-litigate)

Two flags. `ops_fence_authority` (`redis|etcd`, default redis) selects the authoritative
backend; `ops_fence_shadow` toggles the dual-write. **HA-off never consults the authority
flag** (stays unconditional Redis single-writer). `get_shadow_fence_store()` returns the
**non-authoritative** backend, so the shadow direction reverses structurally at cutover
(no second flag).

Resolved forks (full text in the arc opener; summary here):

1. **First-boot data continuity.** `authority=etcd` + empty etcd blob → silent CP-state
   loss. Fix (both): documented **shadow-on precondition** to cutover, **and** a
   **read-only** Redis-blob fallback in `restore_store` when the etcd blob is absent, logged
   loudly. Read-only because restore runs at boot before election — an etcd write there
   would be unfenced. etcd warms at the promotion-time persist (`main.py` ~`write_fence`) on
   first election, so the window is seconds. **This fallback DIES in 5b** — permanent, it
   becomes a stale-state resurrection hazard after any future etcd data loss.
2. **`s04` reframe.** Post-cutover a primary↔Redis partition no longer touches durable
   writes (Redis = caches + pub/sub). Rewrite `s04` as a positive **"durable authority
   survives Redis loss"** test (the arc's headline capability), not a red scenario.
3. **Dual-write removal timing.** Land 5a with the shadow **reversed** (Redis shadows etcd)
   for a soak at 0 divergence; remove the dual-write in **5b** (separate commit) — don't
   discard the observation window in the landing that first exercises etcd authority.
4. **Offload via `asyncio.to_thread`** (copies context → the `write_fence` ContextVar that
   `resolve_write_fence_term` reads propagates; a raw `run_in_executor` would drop it).
   `restore→demote→raise` must complete **inside** the offloaded call (it does — it's all
   inside `persist_store`).
5. **Mutation lock (critical, ships with the offload).** The blocking sync-in-async handlers
   were **accidentally serializing** web mutations. `to_thread` introduces true handler
   concurrency → two read-modify-write cycles under the **same valid term** race, both
   CAS-accepted (CAS fences terms, not writers within a term), a stale-payload write lands
   last, first mutation lost. Add a process-level `asyncio.Lock` around the offloaded
   persist + a **two-writer test**.
6. **EtcdFenceStore failover on the authoritative path** — correct-but-bounded; the ladder
   runs in the offloaded thread, not the loop.
7. **Harness observables flip** to etcd artifacts (prepared in step 3), keyed on authority;
   prove `assert_durable_unchanged` is non-vacuous (would actually fail if the blob changed).
8. **`/ops/ha` term display keys off authority** (5b): post-cutover the Redis-derived
   `fence_term` goes stale.
9. **Contract updates** (5a): `deploy/MULTI_CLOUD.md` §Control-plane HA + `CLAUDE.md`
   invariants — durable writes now the etcd txn-CAS; unelectable limitation **resolved**;
   boot restore needs etcd (+ the read-only Redis fallback); bump the "Verified baseline".

**Two discovered necessities (flagged, agreed as forced consequences):**
- **Reverse-shadow needs shadow-*promote*, not just persist.** Under `authority=etcd` the
  Redis term is no longer maintained by the election, so `RedisFenceStore.cas_persist` would
  reject on a stale term → false "diverge". So `promote_redis_fence` also mirrors the promote
  (keeps the shadow term current). Harmless forward (etcd shadow-promote is idempotent).
- **`s07` reframes with `s04`.** `s07` (external *Redis* fence bump → demote) tests a
  Redis-CAS property that's gone post-cutover. Reframe: bump the *etcd* term, assert the etcd
  CAS rejects the stale writer → demote.

---

## Step 5a — DONE (uncommitted store core; 277 unit pass)

All in `app/ops/store.py` + `app/core/config.py` + `tests/conftest.py`:

- `config.py`: added `ops_fence_authority: str = "redis"` (below `ops_fence_shadow`).
- `store.py`:
  - `_build_authoritative_store()` → `EtcdFenceStore(settings.ops_etcd_endpoints, timeout=2.0)`
    (**all endpoints → failover**) when `ops_ha_active() and ops_fence_authority=="etcd"`, else
    `RedisFenceStore()`. `get_fence_store()` / `reset_fence_store()` use it.
  - `get_shadow_fence_store()` returns the **other** backend: `authority=etcd` → `RedisFenceStore`
    (bounded by its 1.0s socket); else bounded single-endpoint `EtcdFenceStore(…, timeout=0.5)`.
    Returns `None` when `not ops_ha_active()`.
  - `EtcdFenceStore.__init__` now takes `endpoints: str | list[str]` (comma-split + normalize);
    `_post` uses `etcd_post_failover` (one endpoint ⇒ single attempt; many ⇒ failover). Import
    `etcd_post_failover` added.
  - `_shadow_compare_persist` → generic `_shadow_compare(op, shadow_call, auth_accept)`; records
    `tess_ops_fence_shadow_total{op,outcome}` match/diverge/unavailable, never raises.
  - `persist_store` shadow call → `_shadow_compare("persist", lambda s: s.cas_persist(term,
    payload), auth_accept)`. `promote_redis_fence` now captures `auth_accept` and, when shadow
    on, calls `_shadow_compare("promote", lambda s: s.promote_term(fence_term), auth_accept)`.
  - `restore_store`: when `ops_ha_active() and authority=="etcd"` and the etcd blob is `None`,
    read-only adopt `RedisFenceStore().read_blob()` with a loud `warning`.
- `conftest.py`: the autouse fixture now also calls `reset_fence_store()` +
  `reset_shadow_fence_store()` (isolation for authority tests).

---

## IMMEDIATE NEXT TASK — `app/api/ops.py` mutation lock + offload

**Why:** post-cutover the durable write is `EtcdFenceStore` (failover, up to ~6s under
degradation). The mutating `/ops/*` handlers are `async def` calling **sync** `persist_store`
directly on the event loop — the same stall class the `/ops/ha` fix (step 3) already cured
once — and, critically, they were accidentally serializing mutations, so the offload must
ship with an explicit lock or it introduces lost updates.

**Pattern.** Add near the top of `app/api/ops.py` (`import asyncio` is already present from
step 3):

```python
_mutation_lock = asyncio.Lock()

async def _fenced_commit(fn=persist_store, /, *args, **kwargs):
    """Serialize + offload a durable write off the event loop (context-preserving).

    asyncio.to_thread copies contextvars so write_fence propagates; the lock serializes
    the offloaded persists so two writers under the same valid term can't lose an update
    (CAS fences terms, not writers within a term). restore->demote->raise runs inside
    persist_store, i.e. inside the offloaded call.
    """
    async with _mutation_lock:
        return await asyncio.to_thread(fn, *args, **kwargs)
```

**Call sites** (replace the bare sync call). Persist sites — `create_provider` (~189),
`update_provider` (~224), `delete_provider` (~243), `connect_provider` (~268), `probe_now`
(~288), `put_routing_policy` (~406), `wake_provider` (~501), `sleep_provider` (~549): change
`persist_store()` → `await _fenced_commit()`. `set_active` (~585): change
`force_active_provider(provider_id, operator_id=operator_id)` →
`await _fenced_commit(force_active_provider, provider_id, operator_id=operator_id)`. Also
check the routing dual/performance handlers (`post_routing_dual` ~411, `post_routing_performance`
~442, and their `delete_*`) — if they call a `routing_modes` helper that persists synchronously,
offload that helper the same way (`await _fenced_commit(enable_dual, …)` etc.). `FenceCasError`
still propagates out of `_fenced_commit` exactly as before (→ 500/503), so handler error
behavior is unchanged.

*Note (verified):* TESS persists the **whole** store blob at persist time, and the in-memory
read-modify-write is synchronous (atomic on the single-threaded loop). So the lost-update risk
is specifically the **concurrent offloaded persists** writing stale full-blob snapshots — which
`_fenced_commit`'s lock serializes. The two-writer test must prove two concurrent
`create_provider` calls both survive.

---

## Then, in order

- **Tests** (`tests/`): a **two-writer** test (two concurrent mutations under one term → both
  survive, no lost update); an authority-switch test (`get_fence_store()` returns Etcd vs Redis
  per `ops_fence_authority`, HA-off always Redis); a `restore_store` etcd-absent → Redis-fallback
  test (read-only, loud). The existing `tests/test_fence_shadow.py` still asserts shadow
  outcomes with an injected `_FakeFenceStore`; the generalized `_shadow_compare` is compatible
  (they run under default `authority=redis`).
- **Harness** (`scripts/ops_cp_splitbrain/`): add authority-aware durable observables
  (`durable_fence_term`/`durable_blob`/`durable_active_provider_id`) that dispatch on
  `OPS_FENCE_AUTHORITY` (etcd helpers `etcd_fence_term`/`etcd_blob`/`etcd_active_provider_id`
  already exist from step 3); point `verify_clean_baseline` + `assert_durable_unchanged` +
  the scenarios at them; **reframe `s04`** (Redis-loss-survival) and **`s07`** (bump the etcd
  term, assert etcd CAS reject → demote); **review `s06`** (quorum loss now blocks durable
  writes entirely — assert the failure is on the durable path). Prove `assert_durable_unchanged`
  is non-vacuous.
- **Contract**: `deploy/MULTI_CLOUD.md` §Control-plane HA + `CLAUDE.md` (see fork 9); mark the
  unelectable limitation resolved; bump "Verified baseline"; update the opener Status (Step 5).
- **Soak + commit 5a**: unit + live-etcd parity green; bring the stack up with
  `OPS_FENCE_AUTHORITY=etcd` **and** `OPS_FENCE_SHADOW=true` (reverse shadow) **both in the
  harness shell**; `run-all` = 10/10; confirm reverse-shadow `outcome="diverge"` == 0 (scrape
  as in step 4 — web `/metrics`, and the in-process worker check since worker task metrics
  aren't exposed on 9109). Commit 5a (all files) with the harness/parity results.
- **5b** (separate commit): remove the dual-write + `_shadow_compare` + `get_shadow_fence_store`
  + `ops_fence_shadow` + the `restore_store` Redis fallback; make `/ops/ha` report the term
  from the authoritative backend (key off `ops_fence_authority`); harness 10/10; update contract
  + opener; PR #10 → "steps 1-5"; push.

---

## Verification (per-step gates — run all three)

1. `python -m pytest tests/ -q` (host). Passes with the etcd contract tests **skipped** —
   green ≠ etcd-verified.
2. **Live-etcd parity** (host, required every step touching the backend): throwaway etcd +
   `OPS_TEST_ETCD_ENDPOINT=http://127.0.0.1:12379 pytest tests/test_fence_store_parity.py`
   (one-liner in the opener §Verification).
3. **Split-brain harness** (Docker): `docker compose -f docker-compose.yml -f
   docker-compose.ops-ha.yml -f docker-compose.ops-obs.yml -p tess-engine up --build -d`
   then `python -m scripts.ops_cp_splitbrain run-all` = 10/10.

**Env gotchas (all one failure mode — non-default env silently dropped; verify flags
IN-PROCESS via a `/metrics` or `docker exec … python -c` scrape, not `printenv`):**
- `OPS_ADMIN_TOKEN` must match the value the web container took from the repo `.env`
  (compose interpolates `${OPS_ADMIN_TOKEN}`). On this host it is
  `d3666a3e5f82a2292e0bc1767438d106c5d5c17b17bfb83ea7d0e7b4caa3d758`. Mismatch → uniform 403.
- Export `OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml` so `s10` can scrape `/metrics`.
- **Any flag you want live during the run (`OPS_FENCE_SHADOW`, `OPS_FENCE_AUTHORITY`) must be
  in the HARNESS shell**, not just the initial `up` — `reset_stack` recreates web via a
  `docker compose` subprocess and `${VAR:-default}` interpolates from *that* env, silently
  reverting the flag after scenario 1.
- etcd is **not** host-published; scrape it via `docker exec … etcdctl` or the parity
  throwaway container.

Harness reference times ~50–80s/scenario on 3-node (~10-12 min for `run-all`).

---

## Invariants to keep green (enforced)

- `tests/test_ops_fencing.py`: `app/worker.py` keeps exactly **6** `check_fence_live`; no
  `require_primary_cached`/`get_role_state`/`mark_primary` in the worker; CAS reject ==
  etcd reject severity (restore + demote + raise `FenceCasError`).
- `tests/test_ops_metrics.py`: `tess_ops_` prefix, allowlisted labels only (`op`, `outcome`,
  `result`, … — no `backend`/`store`/`provider_id`).
- CLAUDE.md rule: harness + `test_ops_fencing.py` + live-etcd parity before every commit on
  this path; update "Verified baseline".
- `EtcdFenceStore` payload-size guard (~1.5 MiB) stays; shadow/authoritative etcd writes
  bounded (shadow single-attempt; authoritative failover in the offloaded thread only).

## Pointers

Arc opener `docs/archive/ops/CP_HA_QUORUM_OPENER.md` · seam `app/ops/store.py` · consensus
`app/ops/consensus.py` · handlers `app/api/ops.py` · harness `scripts/ops_cp_splitbrain/`
(`config.py`, `harness.py`, `observables.py`, `docker_util.py`, `scenarios/`) · contract
`deploy/MULTI_CLOUD.md` + `CLAUDE.md` §"Ops control-plane HA".
