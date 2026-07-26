# W1.5 — Offline-Verifier Topology Re-Sync — Opener (resume here)

Cold-start doc for **W1.5** of the [Next-Steps Program](NEXT_STEPS_PLAN.md): repair the
offline bundle's split-brain verification step and restore **full failover certification**
for sovereign deploys. Small (~1 short session) but it closes a **certification gap on a
product surface** — since the arc's Step-3 3-node-etcd cutover, no offline bundle has passed
its own full verifier, and `deploy/MULTI_CLOUD.md` §Offline currently documents that honestly
as a **Known gap**. This work deletes that block by making it true again.

Filing with diagnosis: [NEXT_STEPS_PLAN.md §W1.5](NEXT_STEPS_PLAN.md). W1 evidence:
PR #11 (`ops/w1-ha-hardening`). All measurements below are from the W1 session
(2026-07-26); the raw logs lived in that session's scratchpad, so **this doc inlines
everything the fresh session needs**.

---

## Start state (verify first)

1. **PR #11 merged** — W1 (rename + lockfile + non-root, 5 commits ending `13bdd13`).
   `git checkout main && git pull`, confirm the merge, then
   `git switch -c ops/w1.5-offline-verifier`.
2. `python -m pytest tests/ -q` → **279 passed, 2 skipped** (unchanged by W1).
   `python -m scripts.check_doc_links` → **0 broken** (~476 links).
3. `gh` at `C:\Program Files\GitHub CLI\gh.exe` (not on PATH). Repo-root `.env` holds
   `OPS_ADMIN_TOKEN` (dev harness); the **offline** stack uses the compose fallback
   `ha-harness-token` (fine for local verification; `--prod` install rejects it).
4. Docker Desktop up, engine healthy — check `docker info` shows **non-zero CPUs** (see
   §Environment notes; a 500-on-every-route engine is a wedge, not a code problem).

---

## What is broken (measured, W1 session 2026-07-26)

**Root cause.** The offline stack ships a **single `etcd` service**
([docker-compose.offline.yml:43](../docker-compose.offline.yml)), but the harness defaults
`etcd_services` to `etcd-1,etcd-2,etcd-3`
([scripts/ops_cp_splitbrain/config.py:72-78](../scripts/ops_cp_splitbrain/config.py)) and
the verifier's runner invocation
([deploy/offline/verify-egress-blocked.sh:102-113](../deploy/offline/verify-egress-blocked.sh))
**never sets `OPS_HA_ETCD_SERVICES`**. Every scenario dies at setup on
`docker compose ps -q etcd-1`.

**Measured results (offline stack, non-root image `62006ee`):**

| Run | Result |
|---|---|
| Default env | **0/11** — every scenario: `FAIL: cmd failed (1): docker compose ... ps -q etcd-1` |
| `OPS_HA_ETCD_SERVICES=etcd`, default 30s convergence | **6/11** — s01/s02/s04/s05/s08/s10 PASS; s03/s06/s07/s09 time out (`timeout waiting for durable[etcd] fence+blob after election`); s11 quorum-only FAIL |
| Same + `OPS_HA_CONVERGENCE_TIMEOUT=60` (the four etcd-fault scenarios re-run) | **all four PASS** (62–68s each); zero permission errors in web logs |
| Earlier root-image diagnostic (pre-`.wslconfig`, ~2× VM memory), 30s budget | **10/11** — s01–s10 PASS, s11 quorum-only FAIL |

So: **s01–s10 are all valid on single-node etcd**; the 30s failures were VM-memory timing
(this laptop's WSL VM is capped at 4GB — etcd-fault recovery takes ~35–60s vs the
dev-tuned `3 × lease_TTL = 30s` default, [config.py:49-50](../scripts/ops_cp_splitbrain/config.py)).
**Only `s11`** (SIGKILL the etcd Raft leader mid-mutation-storm, expect durable writes to
resume on a surviving quorum member) is **inapplicable to single-node** — with no survivor,
writes correctly stay blocked (sustained 503s is *right* there, so its current expectation
cannot pass).

**Stale "10/10" claims to kill (all four):**
`verify-egress-blocked.sh:8` (header), `verify-egress-blocked.sh:136` (**attestation
text**), `install-offline.sh:123` (next-step hint), `build-bundle.sh:153` (next-step hint).

**Adjacent finding (dev harness, optional Step 4):**
[harness.py:34-63](../scripts/ops_cp_splitbrain/harness.py) `reset_stack` recreates only
CP + etcd (`--no-deps`) + starts redis; from a **fully torn-down project** it never creates
`worker`/`otel-collector`, so `s10` fails on worker-metrics reachability
(`127.0.0.1:9109` refused). Repro: `docker compose ... down --remove-orphans`, then
`run-all` without a prior full `up`.

---

## Invariants (inherited)

- **A harness failure is a product bug until proven otherwise** — this work fixes the
  verifier's *wiring and topology model*, never softens a product assertion.
- **Topology-keyed, never blanket.** A 3-node run must still **execute** s11. The dev
  `run-all` stays **11/11 with s11 executed** — that is the non-vacuity proof that the
  gating keys on topology rather than skipping globally.
- **Skips are explicit.** The offline tally must show s11 as SKIPPED-with-reason
  (topology: quorum-only), never silently absent. Assertions target artifacts, not log
  strings.
- W1.5 touches **no product files** (`app/ops/*`, `app/api/ops.py` unchanged), so the
  CLAUDE.md full ladder (parity etc.) is not triggered — but the harness itself changes,
  so **dev `run-all` 11/11 is required anyway** (the verifier must not be weakened).

---

## Steps (each gated)

### Step 1 — env plumbing

`verify-egress-blocked.sh`'s runner `docker run` gains
`-e OPS_HA_ETCD_SERVICES=etcd` and a realistic convergence budget.
- **Gate:** offline chain reaches the harness and scenarios actually run (no 0/11-at-setup).
- **Non-vacuity:** with the new env line removed, 0/11 reproduces.

### Step 2 — topology-keyed s11 gating

Key on `len(cfg.etcd_services) == 1` (single-node) → s11 reports an explicit SKIP;
≥3 services → s11 runs as today.
- **Gate:** offline `run-all` = **10 PASS + 1 SKIP(topology), exit 0**; dev `run-all`
  still **11/11 with `[PASS] s11` present in the summary** (proves the gate is
  topology-keyed, not blanket).

### Step 3 — re-baseline + kill stale text + restore the certification claim

Verifier asserts the topology-aware expected tally; fix all four "10/10" sites (§above —
including the **attestation** at `verify-egress-blocked.sh:136`); in
`deploy/MULTI_CLOUD.md` §Offline replace the **Known gap** block with the restored
failover-certification claim (with the topology note), and update the runbook line.
- **Gate:** full chain `build-bundle.sh → install-offline.sh → verify-egress-blocked.sh`
  **exits 0 end-to-end**; doc-links 0 broken.

### Step 4 (optional, recommended) — `reset_stack` first-run robustness

After `compose_recreate`, if a service in the file set has no container (worker), fall
through to full `compose_up(cfg)`.
- **Gate:** from a fully torn-down project, dev `run-all` → 11/11 (the W1 s10 repro now
  green). If skipped as code, add the "bring the full stack up once before `run-all`"
  runbook note to `scripts/ops_cp_splitbrain/README.md` instead.

---

## Decisions to make at session start

1. **s11 single-node: explicit SKIP (recommended for W1.5)** vs a single-node variant
   asserting the *correct* behavior (503s while the sole etcd is down → durable writes
   resume after restart). The variant is the better long-term cure (turns a skip into an
   assertion) — file it as a stretch/W2-era item if not done here.
2. **Convergence budget: derive, don't hardcode** (recommended: pass `6 × lease_TTL`
   via the existing `OPS_HA_CONVERGENCE_TIMEOUT` env — consistent with how TTL already
   parameterizes the harness) vs a fixed `60`.
3. **Step 4 as code vs runbook note.** Recommended: code — one guarded `compose_up`, and
   the repro exists to gate it.

---

## Verification env (exact commands, proven in the W1 session)

**Offline chain** (build needs a **clean tree** — commit first):
```bash
deploy/offline/build-bundle.sh                    # writes tess-offline-bundle-<sha>.tar.gz
mkdir -p /tmp/w15 && tar -xzf tess-offline-bundle-*.tar.gz -C /tmp/w15
cd /tmp/w15 && ./install-offline.sh --target /tmp/w15/install
./verify-egress-blocked.sh --target /tmp/w15/install    # after Step 3: exit 0
```

**Manual runner** (pre-fix repro / debugging — this is the invocation that produced the
measurements above; on Git-Bash use `MSYS_NO_PATHCONV=1` and `cygpath -w` for the mount):
```bash
docker run --rm --network tess-engine_default \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "<win-path-to-install-dir>:/work" -w /work \
  -e OPS_HA_SMOKE_A=http://tess-engine-web-1:8000 \
  -e OPS_HA_SMOKE_B=http://tess-engine-web-standby-1:8000 \
  -e OPS_HA_WORKER_METRICS=http://tess-engine-worker-1:9109 \
  -e OPS_HA_COMPOSE_BASE=docker-compose.offline.yml \
  -e OPS_HA_COMPOSE_OVERLAY= -e OPS_HA_COMPOSE_OBS= \
  -e OPS_HA_ETCD_SERVICES=etcd \
  -e OPS_HA_CONVERGENCE_TIMEOUT=60 \
  -e OPS_ADMIN_TOKEN=ha-harness-token \
  tess-engine-harness-runner:offline \
  python3 -m scripts.ops_cp_splitbrain run-all
```

**Dev regression** (required — the harness changes):
```bash
# Bring the FULL stack up first (reset_stack gap — see Step 4):
docker compose -f docker-compose.yml -f docker-compose.ops-ha.yml \
  -f docker-compose.ops-obs.yml -p tess-engine up --build -d
export OPS_ADMIN_TOKEN=<value from repo-root .env>
export OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml
python -u -m scripts.ops_cp_splitbrain run-all          # 11/11, s11 EXECUTED
```

---

## Environment notes (this laptop — learned the hard way in W1)

- **WSL2 is capped**: `.wslconfig` `memory=4GB swap=4GB` (set after an OOM wedge; C: was
  extended +105GB afterward, so the cap could be raised if a run needs it). Harness
  etcd-fault recovery takes **~35–60s** here — budget accordingly.
- **One stack at a time.** Dev and offline share the compose project `tess-engine` — tear
  one down before bringing up the other. The verifier's structural check fails on any
  non-internal container left in the project.
- **Engine wedge mid-run** (500 on every Docker API route, `docker info` → `CPUs=0`) =
  environment flake: restart Docker Desktop (or `wsl --shutdown` from a normal terminal,
  then relaunch), re-run the gate. **Don't suspect the code** — but do re-run, never
  half-count a wedged run.
- The offline stack has `restart: unless-stopped` — it **auto-revives after a
  reboot**; check `docker ps` before assuming a clean slate.

---

## Landing

Branch `ops/w1.5-offline-verifier`; two or three small commits (env plumbing + gating;
re-baseline + docs; optional `reset_stack`), PR into main. Close by flipping
[NEXT_STEPS_PLAN.md §W1.5](NEXT_STEPS_PLAN.md) to **DONE**, deleting the MULTI_CLOUD
**Known gap** block (Step 3), and adding the ROADMAP line. Then **W2** (expand its opener
from NEXT_STEPS_PLAN §W2, same shape as this one) — where the offline chain joins the
**nightly CI tier** so it can never rot invisibly again.
