# W1 — Ops/HA Hardening — Opener (resume here)

Cold-start doc for **W1** of the [Next-Steps Program](NEXT_STEPS_PLAN.md): clear the two
deferred HA-hardening items + the cosmetic fence rename. Small, but it touches the ops/HA +
container surface, so it inherits the arc's gate discipline. Read the arc opener
[CP_HA_QUORUM_OPENER.md](archive/ops/CP_HA_QUORUM_OPENER.md) for the verification env and the
non-vacuous-evidence rule this reuses.

---

## Start state (verify first)

1. **PR #10 is merged** — W1 starts from `main` containing the CP-HA arc (`44645c2`).
   `git checkout main && git pull`, then `git log --oneline -1` should show the arc merge.
   Branch W1 off main: `git switch -c ops/w1-ha-hardening`.
2. `python -m pytest tests/ -q` → **279 passed, 2 skipped** (the W1 baseline).
3. `gh` at `C:\Program Files\GitHub CLI\gh.exe` (not on PATH). Repo-root `.env` holds
   `OPS_ADMIN_TOKEN` (harness auth — mismatch → uniform 403).
4. Docker Desktop up; the HA+obs stack builds with the three compose files (base +
   `docker-compose.ops-ha.yml` + `docker-compose.ops-obs.yml`).

---

## Invariants that must not break (inherited from CLAUDE.md)

W1 is **behavior-preserving** — it changes names, container users, and dependency *pinning*,
never fence logic. So every arc invariant still holds and is the pass bar:

- All durable ops writes go through the fence; `app/worker.py` has **exactly 6**
  `check_fence_live` and no cached-role APIs; a CAS reject == an etcd reject (demote + raise).
- Harness assertions target artifacts (Redis/etcd term+blob, HTTP bodies), never log strings.
- Metrics: `tess_ops_` prefix, allowlisted labels only.
- **The rename is a pure symbol change** — no call-site semantics change. **Non-root must not
  change container behavior** (etcd/redis volume perms, the in-container split-brain runner).
  **The lockfile must preserve exact versions** — no silent upgrades.

---

## Three commits — one harness-verified commit per change (arc rule)

Independent; recommended order below (rename first = fastest feedback). **Do not batch** —
each is its own certification boundary.

### Commit 1 — rename `promote_redis_fence` → `promote_fence`

Authority-agnostic post-cutover, so the old name is now a misnomer.

- **Code:** `app/ops/store.py` (the `def` + any internal refs), `app/main.py` (caller).
- **Guard:** `tests/test_ops_fencing.py` references the symbol — **update it in the same
  commit** so the guard tracks the new name (same rule the arc used for banned symbols).
- **Living docs:** update `deploy/MULTI_CLOUD.md` and `scripts/ops_cp_splitbrain/README.md`.
  **Leave the archived arc docs** (`docs/archive/ops/*`, `docs/CP_HA_*REPORT*`) — they are
  historical snapshots; a lingering old name there is accurate history, not a bug.
- **Gate (store.py FenceStore path → full ladder):** unit + `tests/test_ops_fencing.py` +
  live-etcd parity 4/4 + split-brain `run-all` **11/11 @etcd** (+ `s11` @redis).
- **Non-vacuity:** confirm the guard would **fail** if the old name lingered (grep the tree
  for `promote_redis_fence` → only archived docs remain).

### Commit 2 — hash-pinned lockfile

- **Dev-time:** `pip-compile --generate-hashes` from `requirements.txt` →
  `requirements.lock.txt` (keep `requirements.txt` as the human-edited top-level; the lock is
  generated). *(Decision settled — see the plan.)*
- **Install path:** `Dockerfile` + `deploy/offline/install-offline.sh` switch to
  `pip install --require-hashes -r requirements.lock.txt`. **No new binary enters the
  zero-network bundle** — the install stays plain pip.
- **Gate:** unit suite green (identical versions → no behavior change); **offline
  `build-bundle.sh` → `install-offline.sh` → `verify-egress-blocked.sh` all green** (the lock
  installs under egress block with hash verification). Split-brain harness **not required**
  (no consensus/store/api change), but rebuild the stack so images use the lock.
- **Non-vacuity:** `--require-hashes` fails the build on any hash/version mismatch — that is
  the proof it's a real gate. Sanity-verify by confirming an intentional bad hash aborts.

### Commit 3 — non-root containers

- **`Dockerfile`** (`python:3.11-slim`, currently no `USER` → root): create a non-root user,
  `chown` the app dir + any writable paths (e.g. the obs `/spans` volume, logs), `USER` before
  `CMD`. Check `frontend/Dockerfile` (build → static serve; likely already non-root or N/A —
  scope at least the Python app + worker).
- **Watch:** the split-brain harness runs an **in-container runner reaching nodes by
  container name** (offline stack) — it must still work non-root; etcd/redis official images
  carry their own users, so the concern is the `web`/`worker` images.
- **Gate:** rebuild stack; `docker exec tess-engine-web-1 whoami` **≠ root**; stack healthy;
  split-brain `run-all` **11/11** (proves non-root didn't break etcd perms or the runner);
  offline `build → install → verify-egress-blocked` green (non-root holds in the offline stack
  too).
- **Non-vacuity:** the `whoami ≠ root` check proves non-root actually took effect (not a
  no-op `USER` after `CMD`).

---

## Verification env (harness shell — identical to the arc)

```bash
export OPS_ADMIN_TOKEN=<value from repo-root .env>
export OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml
python -u -m scripts.ops_cp_splitbrain run-all                 # 11/11 @etcd
OPS_FENCE_AUTHORITY=redis python -u -m scripts.ops_cp_splitbrain run s11_kill_etcd_leader_storm
```

Live-etcd parity (throwaway single-node etcd on `:12379`, then
`OPS_TEST_ETCD_ENDPOINT=http://127.0.0.1:12379 pytest tests/test_fence_store_parity.py`) and
the doc-links checker (`python -m scripts.check_doc_links` → 0 broken) — see the arc opener
§Verification for the exact etcd `docker run` and the env gotchas (non-default env silently
dropped on compose-recreate; verify flags in-process).

---

## Landing

Three commits on `ops/w1-ha-hardening`, small PR into main. Close W1 by flipping
`deploy/MULTI_CLOUD.md` §Deferred hardening (non-root + lockfile) to **done**, and updating
the plan's W1 section + `ROADMAP.md`. No open decisions block W1 (lockfile tool is settled;
the other five plan decisions belong to later workstreams).
