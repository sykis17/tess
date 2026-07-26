# CP-HA Quorum Fence Store — Step 5b hand-off (resume here)

> **STATUS: COMPLETE — arc closed.** Step 5b landed: dual-write / reverse shadow retired,
> `ops_fence_shadow` + shadow metric + read-only Redis restore fallback removed. Gates green
> (unit 279/2, live-etcd parity 4/4, split-brain `run-all` 11/11 @etcd + `s11` @redis). Docs
> updated (CLAUDE.md, MULTI_CLOUD.md, ROADMAP, arc opener). This doc is retained as the
> resume record; nothing below is outstanding.

Hand-off for a fresh session to finish **Step 5b** — the arc closer (remove the dual-write /
shadow machinery). Steps 1–6 are committed + pushed; **5b code is written and unit-green but
UNCOMMITTED**, and its harness/parity gates have not run yet. Read the arc opener
[`CP_HA_QUORUM_OPENER.md`](CP_HA_QUORUM_OPENER.md) and the step-5 hand-off
[`CP_HA_QUORUM_S5_HANDOFF.md`](CP_HA_QUORUM_S5_HANDOFF.md) for arc context.

---

## TL;DR — resume in 5 moves

1. `git status` should show the **uncommitted 5b WIP** below on tip `23c9ed9` (Step 6).
   `python -m pytest tests/ -q` → **279 passed, 2 skipped**. If the WIP is missing, it was not
   committed — reconstruct from §"What 5b removed".
2. **Rebuild the stack** (the running containers are Step-6 images that still have the shadow):
   `docker compose -f docker-compose.yml -f docker-compose.ops-ha.yml -f docker-compose.ops-obs.yml -p tess-engine up --build -d`.
3. **Live-etcd parity** (REQUIRED — the `store.py` CAS-path wrappers changed): throwaway etcd on
   `:12379`, then `OPS_TEST_ETCD_ENDPOINT=http://127.0.0.1:12379 pytest tests/test_fence_store_parity.py` → 4/4.
4. **Harness run-all** (now defaults to `authority=etcd`, no shadow): `run-all` → **11/11**, and
   `OPS_FENCE_AUTHORITY=redis` `run s11...` green. (Env exports in §Verification.)
5. **Docs** (§Docs remaining), then **commit 5b** (all files) + push + PR #10 → full arc.

Do **not** commit partial 5b — one harness-verified commit per step.

---

## Exact state (verified at hand-off)

- Branch `cursor/cp-ha-quorum-fence-store`, tip **`23c9ed9`** (Step 6, pushed). PR #10 open
  ("steps 1-6").
- **Uncommitted 5b WIP** (unit-green, 279/2):
  - Product: `app/ops/store.py`, `app/core/config.py`, `app/ops/metrics.py`,
    `docker-compose.ops-ha.yml`.
  - Tests: `tests/test_fence_shadow.py` **(git-rm'd / deleted)**, `tests/test_fence_store_authority.py`,
    `tests/conftest.py`.
  - Harness: `scripts/ops_cp_splitbrain/observables.py`,
    `scripts/ops_cp_splitbrain/scenarios/s11_kill_etcd_leader_storm.py`.
- Docker stack is **UP but running Step-6 images (WITH the shadow)** — rebuild before the harness
  (move 2) or it tests the wrong code.
- `gh` at `C:\Program Files\GitHub CLI\gh.exe` (not on PATH). Repo `.env`
  `OPS_ADMIN_TOKEN=d3666a3e5f82a2292e0bc1767438d106c5d5c17b17bfb83ea7d0e7b4caa3d758`.

---

## What 5b removed (DONE, uncommitted; unit-green)

The etcd cutover shipped in 5a; the reverse shadow was a divergence safety-net kept only until
Step 6's leader-kill storm proved `diverge==0`. 5b retires it:

- **`app/ops/store.py`**: deleted the whole shadow block (`SHADOW_TIMEOUT_SECONDS`, `_shadow_store`,
  `get_/set_/reset_shadow_fence_store`, `_shadow_compare`); removed the `if settings.ops_fence_shadow:
  _shadow_compare(...)` calls from `persist_store` **and** `promote_redis_fence`; removed the
  `restore_store` read-only Redis fallback — an absent etcd blob now returns `False` with a **loud
  warning** ("no Redis fallback after the etcd cutover; recover explicitly"); deleted the dead
  `read_redis_fence_term`; dropped the now-unused `first_etcd_endpoint` (+ `etcd_post`) imports.
- **`app/core/config.py`**: removed the `ops_fence_shadow` field. (`ops_fence_authority` **stays** —
  etcd default, redis opt-in legacy.)
- **`app/ops/metrics.py`**: removed the `FENCE_SHADOW` counter, `record_fence_shadow`, and the two
  `FENCE_SHADOW` references (`ALL_METRICS` list + the no-prometheus `None` fallback line).
- **`docker-compose.ops-ha.yml`**: removed the three `OPS_FENCE_SHADOW: ${OPS_FENCE_SHADOW:-true}`
  env lines (kept `OPS_FENCE_AUTHORITY: ${OPS_FENCE_AUTHORITY:-etcd}`).
- **Tests**: deleted `test_fence_shadow.py`; in `test_fence_store_authority.py` removed the
  shadow-direction test and **flipped** the migration-fallback test to
  `test_restore_no_redis_fallback_when_etcd_blob_absent` (absent etcd blob → `restore_store()` is
  `False`, loud warning, the stale Redis blob is **not** resurrected, etcd never written);
  `conftest.py` dropped `reset_shadow_fence_store`.
- **Harness**: `s11` dropped the reverse-shadow assertions (`shadow_before` gate + the
  `diverge==0`/`match`-advanced block) — that soak evidence is banked in the Step-6 commit;
  everything else (SIGKILL leader, block-and-resume, Raft-term non-vacuity, monotonic term,
  no-corruption) stays. `observables.py` dropped `shadow_totals`.

**Note — `/ops/ha` term display (fork 8): already correct, no change needed.** `get_ha_status`
shows `role.fence_term` (election/etcd-derived) + `etcd_fence_term` (live etcd read); there was no
Redis-derived term in the display. The only Redis-term reader was the dead `read_redis_fence_term`
(now removed). If you want, rename `promote_redis_fence` → `promote_fence` for honesty (it is
authority-agnostic now) — **cosmetic, deferred**; touches `main.py`, `worker.py`?, tests, CLAUDE.md.

---

## Remaining — gates, in order

1. **Rebuild** (move 2 above) — required so the harness tests 5b code, not the Step-6 images.
2. **Live-etcd parity** (move 3) — 4/4. Required by the CLAUDE.md invariant (CAS path changed).
3. **Harness run-all** (move 4) — `11/11 @ authority=etcd` (default now) AND `s11 @ authority=redis`.
   s11 no longer scrapes the shadow, so no obs dependency for its assertions (obs overlay still
   needed for s10). Expected times ~50–85s/scenario (~13 min run-all).

## Docs remaining (before commit)

- **`CLAUDE.md` §"Ops control-plane HA — critical invariants"**:
  - Durable-writes bullet: drop "still used as the reverse-shadow" — Redis is now caches + pub/sub
    (durable path) with `authority=redis` as the pure opt-in legacy backend.
  - Verified-baseline bullet: add **Step 5b** (this commit) — dual-write/shadow removed; **remove**
    the pre-commit gate clause "confirming the reverse-shadow `…{outcome="diverge"}` stays 0" (the
    metric is gone). Keep harness + fencing tests + live-etcd parity.
  - Unelectable-limitation bullet: it is now **unconditionally** resolved (the redis-authority
    backend remains an opt-in legacy, but the default has no dual term store).
- **`deploy/MULTI_CLOUD.md` §"Quorum Fence Store: etcd cutover"**: remove the reverse-shadow
  paragraph + the `diverge==0` soak line; state etcd is the sole durable store, no dual-write; the
  `restore_store` "read-only Redis fallback" note becomes "no fallback — loud explicit recovery".
- **`docs/archive/ops/CP_HA_QUORUM_S5_HANDOFF.md`**: mark 5b done (it currently says "Next = 5b").
- Arc opener Status / ROADMAP CP-HA subsection: mark the arc **complete** (steps 1–6 + 5b).

## Commit 5b

`git add -A` (captures the delete + mods), commit `ops(cp-ha): step 5b — retire the dual-write /
reverse shadow (Quorum Fence Store closes)`, push, then PR #10 → title/body through 5b (the arc is
now complete: linearizable etcd durable authority, Redis = caches + pub/sub only).

---

## Verification env (harness shell)

```
export OPS_ADMIN_TOKEN=d3666a3e5f82a2292e0bc1767438d106c5d5c17b17bfb83ea7d0e7b4caa3d758
export OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml
# authority defaults to etcd now; export OPS_FENCE_AUTHORITY=redis only for the legacy path.
python -m scripts.ops_cp_splitbrain run-all           # 11/11 @ etcd
OPS_FENCE_AUTHORITY=redis python -m scripts.ops_cp_splitbrain run s11_kill_etcd_leader_storm
```

Throwaway etcd for parity (single-node; entrypoint IS `etcd`, pass only flags):
```
docker run -d --name tess-parity-etcd -p 127.0.0.1:12379:2379 quay.io/coreos/etcd:v3.5.32 \
  etcd --name p0 --advertise-client-urls http://0.0.0.0:2379 --listen-client-urls http://0.0.0.0:2379 \
  --initial-cluster p0=http://0.0.0.0:2380 --listen-peer-urls http://0.0.0.0:2380 \
  --initial-advertise-peer-urls http://0.0.0.0:2380
OPS_TEST_ETCD_ENDPOINT=http://127.0.0.1:12379 python -m pytest tests/test_fence_store_parity.py -q
docker rm -f tess-parity-etcd
```

**Gotchas** (unchanged from the arc): non-default env silently dropped on compose-recreate — verify
flags in-process; `OPS_ADMIN_TOKEN` mismatch → uniform 403; etcd members are not host-published
(use the throwaway for parity). Python block-buffers piped stdout — run `run-all` with `python -u`
or read the tee log to monitor live.
