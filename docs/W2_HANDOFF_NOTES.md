# W2 — Handoff notes from the W1.5 session (2026-07-27)

> **Folded into [W2_OPENER.md](W2_OPENER.md) (2026-07-27) — historical; start there.**

Session-local knowledge for expanding the **W2 opener** (chain instrumentation + eval
harness + CI; the filing is [NEXT_STEPS_PLAN.md §W2](NEXT_STEPS_PLAN.md) and
§Cross-cutting — CI). These are **notes to fold in, not the opener itself** — the opener
gets written at W2 session start, with the open decisions settled first. Everything below
is measured/verified in the W1.5 session; raw logs die with that session's scratchpad, so
the numbers are inlined.

---

## Start state (verify first)

1. **PR #12 merged** — W1.5 (5 commits ending with these notes). `git checkout main &&
   git pull`, then branch for W2.
2. `python -m pytest tests/ -q` → **289 passed, 2 skipped**.
   `python -m scripts.check_doc_links` → **0 broken**.
3. W1.5 evidence lives in the PR #12 body (gate table) and
   [NEXT_STEPS_PLAN.md §W1.5](NEXT_STEPS_PLAN.md) DONE block. Offline bundle:
   **failover-certified**, 472 MB, built at the W1.5 head.
4. No stacks should be running (`docker ps`) — but the offline stack auto-revives after a
   reboot (`restart: unless-stopped`); check before assuming a clean slate.

## What W1.5 handed W2 (new tooling CI will lean on)

- **`run-all --expect-pass N --expect-skip N`** (`scripts/ops_cp_splitbrain/__main__.py`):
  the expected tally as an exit-code artifact. CI invocations: dev =
  `--expect-pass 11 --expect-skip 0` (proves s11 executed); offline verifier already pins
  `--expect-pass 10 --expect-skip 1` internally (a deliberate certification baseline —
  adding a scenario is *supposed* to break the chain until re-baselined, at the commented
  site in `deploy/offline/verify-egress-blocked.sh`).
- **Topology skips**: scenario modules may declare `skip_reason(cfg)` (s11 keys on
  `len(cfg.etcd_services) < 3`). Unit-tested in `tests/test_splitbrain_topology_gate.py`
  (also covers the argparse→exit-code wiring with docker patched out — the pattern to copy
  for cheap harness tests).
- **Cold-start `run-all`**: `reset_stack` falls through to full `compose up` when `worker`
  has no container — a nightly CI job can run from a torn-down project without a pre-up
  step (proven: torn-down dev run-all 11/11).
- **`build-bundle.sh` size ceiling**: dies if the app image exceeds `MAX_APP_IMAGE_GB`
  (default 3). **Gotcha:** the gate reads `docker image inspect -f '{{.Size}}'`, which on
  this engine (containerd store) reports *content* size (~255 MB for the current app
  image) — `docker images` shows ~1.14 GB unpacked. Tune the ceiling against the inspect
  number.
- **`.dockerignore` now excludes repo-root bundles** — the 17.6 GB image / 8.7 GB bundle
  bloat class is dead. Bundles still land in the repo root (git- and docker-ignored).

## Measured wall-clock (this laptop — budget nightly CI against these)

| Leg | Time |
|---|---|
| `build-bundle.sh` (pip layer cached) | ~4 min |
| `install-offline.sh` (load + up + smoke) | ~2–3 min |
| `verify-egress-blocked.sh` (structural + egress + harness 10+1) | ~13 min |
| **Offline chain total** | **~20 min** |
| Dev `run-all` 11/11 from torn-down (incl. initial full up) | ~17–20 min |
| Offline per-scenario (single-node, 6×TTL=60s budget) | 57–76 s |
| Dev per-scenario (3-node, default 3×TTL=30s budget) | 76–123 s (s06 slowest) |
| Full pytest | ~7 s |

Convergence: single-node etcd-fault recovery needs the 6×TTL budget; the 3-node dev
election is comfortably inside the 30s default even on the capped VM.

## Exact gate commands (proven this session)

```bash
# dev (3-node), from repo root; OPS_ADMIN_TOKEN from repo-root .env
export OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml
python -u -m scripts.ops_cp_splitbrain run-all --expect-pass 11 --expect-skip 0

# offline chain (clean committed tree required)
deploy/offline/build-bundle.sh
rm -rf /tmp/w2 && mkdir -p /tmp/w2 && tar -xzf tess-offline-bundle-<sha>.tar.gz -C /tmp/w2
cd /tmp/w2 && ./install-offline.sh --target /tmp/w2/install
./verify-egress-blocked.sh --target /tmp/w2/install     # exit 0 == enforced 10+1 tally

# legacy backend re-check (only when touching the fence path — not needed for W2 graph work)
OPS_FENCE_AUTHORITY=redis python -u -m scripts.ops_cp_splitbrain run-all
```

A plain `pytest tests/` **skips** the live-etcd parity contract
(`tests/test_fence_store_parity.py`) — green alone does not prove the etcd backend.
Irrelevant for graph-only W2 commits, load-bearing the moment CI wires the parity leg.

## This-laptop profile (unchanged from W1.5, plus two new)

- WSL2 capped at `memory=4GB swap=4GB` (`.wslconfig`); C: has ~100 GB free headroom, so
  the cap can be raised if a CI-style parallel run needs it.
- **One stack at a time** — dev and offline share compose project `tess-engine`.
- Engine wedge = `docker info` shows `CPUs=0`, 500s on every route → restart Docker
  Desktop / `wsl --shutdown`; re-run the whole gate, never half-count.
- `gh` at `C:\Program Files\GitHub CLI\gh.exe` (not on PATH). House merge style: merge
  commits (`gh pr merge N --merge`).
- Git-Bash docker mounts need `MSYS_NO_PATHCONV=1` + `cygpath -w` for `-v` paths.
- **New:** PowerShell 5.1 mangles embedded double quotes in here-string args to native
  commands (git parses message fragments as pathspecs and the commit silently no-ops) —
  write commit/PR bodies to a file, use `git commit -F` / `gh pr create --body-file`.
- **New:** the harness runner mounts the install dir at `/work` and runs
  `python3 -m scripts.ops_cp_splitbrain` from there — harness code comes from the
  **mounted tree**, so you can iterate on harness changes against a live offline stack by
  mounting the repo instead of rebuilding the bundle.

## W2-relevant repo facts

- **No `.github/` exists** — CI starts from zero; the four manual gates + eval are the
  ladder to encode (§Cross-cutting — CI).
- Graph metrics twin: mirror `tests/test_ops_metrics.py` (label allowlist, banned
  unbounded labels, `record_*` never raises) as `tests/test_graph_metrics.py` — required
  by §W2, and the ops version is a direct template.
- The otel-collector + spans-file plumbing W2 needs is already in
  `docker-compose.ops-obs.yml` + `deploy/otel-collector-config.yaml` (s10 proves the
  span path end-to-end).
- **W2-era follow-ups already filed** (NEXT_STEPS §W1.5 DONE block): s11 single-node
  variant (skip → assertion); archive `docs/CP_HA_ENGINEERING_REPORT.md` under
  `docs/archive/ops/` (its pre-s11 "10/10" prose is a dated snapshot, deliberately
  exempted from the W1.5 stale-text sweep).

## Decisions to settle before the opener is final (from §W2)

1. **Trace/metric sink** for per-run history: OTLP→collector (already present) vs Redis
   vs sqlite.
2. **Eval scoring**: LLM-judge vs deterministic rubrics vs both (§W2 recommends both) —
   including the nightly judge **token budget** (pin a cheap fixed judge model, cap the
   golden set; deterministic checks carry the per-push signal). Note the offline profile
   is Ollama-only — a local judge is the zero-spend option, at rubric-quality cost.
3. **Golden-set source/size**: hand-authored ~15–25 prompts spanning L0–L4 × product
   modes.
