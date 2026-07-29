# P1 — Nightly CI tier (`nightly.yml`) — Opener (resume here)

Cold-start doc for the **Proof Program's P1 phase** ([PROOF_PROGRAM.md](PROOF_PROGRAM.md)
§P1), which *is* the deferred W2 Session 3 — the owner clause ("owner: the session after
W3") has fired. Today four proof surfaces are manual discipline: the split-brain harness,
the offline verifier chain (the path that already **rotted once** from exactly this
deferral — [W1_5_OFFLINE_VERIFIER_OPENER.md](W1_5_OFFLINE_VERIFIER_OPENER.md)), the
LLM-bearing eval gate, and the flag-on checkpoint/resume leg (PR #16 residual — the
pre-PR flag-on manual live smoke is what caught P0.1/C7). This session wires them into a scheduled
`nightly.yml` plus one per-push `redis-parity` job, each leg gated by its existing
tally-as-exit-code artifact and each proven **non-vacuous by a planted violation**
before its green is trusted. Why before P2–P4: the soaks generate weeks of data on a
system that must not silently regress mid-soak — nightly CI is what makes "frozen and
still healthy" a checked claim instead of an assumed one.

Filing: [PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P1 (scope deferred to
[W2_OPENER.md](W2_OPENER.md) §Session 3 runway; budget doctrine in
[NEXT_STEPS_PLAN.md](NEXT_STEPS_PLAN.md) §Cross-cutting — CI). Authoring plan reviewed
by Jesse 2026-07-29 — 4 findings (public repo confirmed; self-hosted security caution;
evidence-retention rule; sabotage carve-out) folded below; advance votes recorded where
marked, but **merge of this PR is the ratification act**. File:line references verified
2026-07-29 at `234b0f8`.

---

## Start state (verify first)

1. **This opener's docs-only PR is merged** — the merge is the ratification act.
   `git checkout main && git pull`, confirm, then `git switch -c ops/p1-nightly-ci`.
2. Baselines: `python -m pytest tests/ -q` → **457 passed, 2 skipped** (re-baseline
   inline if main moved); `python -m scripts.check_doc_links` → **0 broken**.
3. **`ci.yml` is still the only workflow file and still promises this session** — both
   greps must hit, else STOP (someone already built nightly, or the promise moved):
   - `land in a separate nightly.yml` in `.github/workflows/ci.yml` (~:2);
   - `ls .github/workflows/` → exactly `ci.yml`.
4. **The four tally pins still read as documented** — verify by **grep, not by
   running** (running every gate is 40+ min; the greps are the drift detector). Any
   drift = STOP and re-diagnose against the interlock table below:
   - `--expect-pass 11 --expect-skip 0` in
     [scripts/ops_cp_splitbrain/README.md](../scripts/ops_cp_splitbrain/README.md)
     (~:60, the dev gate);
   - `--expect-pass 10 --expect-skip 1` at
     [deploy/offline/verify-egress-blocked.sh](../deploy/offline/verify-egress-blocked.sh)
     (~:131, baked into the in-container invocation);
   - `skipped == 2` at [.github/workflows/ci.yml](../.github/workflows/ci.yml) (~:51,
     the unit job's junit assert);
   - `--expect-pass 5` / `--expect-pass 20` in
     [scripts/graph_eval/README.md](../scripts/graph_eval/README.md) (~:17-18).
5. **Local infra for the sabotage/measure loop**: docker up; host Ollama serving
   `llama3.2` (`curl localhost:11434/api/tags`). The nightly legs run on GH runners,
   but Step 1's YAML is iterated from this laptop and local re-runs remain the triage
   path.
6. **Repo is public** — re-verify, don't trust the record:
   `gh repo view --json visibility` → `PUBLIC`. Consequences: Actions minutes are
   free; the `workflow_dispatch`-requires-default-branch constraint stands (hence
   Step 1's temporary push trigger); the self-hosted caution in Resolved question (a)
   is live, not hypothetical.

---

## Settled decisions + attached requirements

1. **Separate `nightly.yml` — DECIDED (W2-S1, `ci.yml:1-3` header), not relitigated.**
   The per-push file is never extended with schedule triggers; job names in `ci.yml`
   are stable API for branch protection.
2. **Nightly job names never join branch-protection required checks** — a
   schedule-only check would block every PR. The per-push `redis-parity` job (Step 5)
   is the one exception candidate: **add it after its first few days green, not
   same-day — DECIDED (2026-07-29, Jesse, plan review)**; the add itself is a
   Jesse-step (branch protection is his console).
3. **Non-vacuity gate per leg** ([PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P1): each
   nightly leg must fail on a planted violation once before its green is trusted — the
   harness sabotage idiom, now applied to the CI wiring itself.
4. **Red-run evidence outlives the logs — DECIDED (2026-07-29, Jesse, plan review):**
   Actions logs/artifacts expire (90-day default retention). The salient failure lines
   from every sabotage run are **pasted into the PR body** (and, where load-bearing,
   into this doc at the docs flip); the run URL is a pointer, never the evidence
   itself. Same family as the review-trail rule in [CLAUDE.md](../CLAUDE.md).
5. **Sabotage carve-out to the scope fence — DECIDED (2026-07-29, Jesse, plan
   review):** planted-violation commits may transiently touch `app/**` (Step 4's
   routing override is the canonical case); each is reverted in the **immediately
   following commit**, and the sabotage+revert pair in main's history IS the evidence.
   Without this carve-out the executor would trip the House-rules fence on its own
   sabotage step.
6. **Judge identity is frozen this arc**: provider default `ollama`, model default
   `llama3.2`, `judge_temperature` hard-pinned `0.0`
   ([scripts/graph_eval/config.py](../scripts/graph_eval/config.py) ~:43),
   `JUDGE_PROMPT_VERSION v1` ([scripts/graph_eval/judge.py](../scripts/graph_eval/judge.py)
   ~:23), `JUDGE_PASS_THRESHOLD 6` (config.py ~:21). The judge runs nightly
   only; deterministic rubrics carry the per-push signal
   ([NEXT_STEPS_PLAN.md](NEXT_STEPS_PLAN.md) §Cross-cutting — CI). Default spend: $0
   (Ollama-local).
7. **Measure-before-pin** (precedent: [W2_S2_OPENER.md](W2_S2_OPENER.md) resolved
   question (c)): no wall ceiling, timeout, disk assumption, or image-size ceiling is
   pinned to CI hardware before a measured run **on that hardware**. Step 1 exists to
   produce those numbers.
8. **Pipefail everywhere in workflow YAML**: `nightly.yml` sets workflow-wide
   `defaults: { run: { shell: bash } }` — GH's *explicit* `shell: bash` runs
   `bash -e -o pipefail`; the *implicit* default does not. This institutionalizes last
   session's "pipes mask exit codes" trap (bit twice) as configuration.
9. **Failure visibility via auto-issue — approved in advance (2026-07-29, Jesse, plan
   review)**: `permissions: issues: write` + an `if: failure()` reporter using the
   preinstalled `gh` CLI and `GITHUB_TOKEN` to open-or-comment a deduped `nightly-red`
   issue. First-party only — no marketplace actions anywhere in the workflow.
10. Advance votes at plan review **de-risk the cold pass, they don't replace it** —
    every decision above marked "plan review" is ratified formally by this PR's merge.

### Re-baseline interlock table (the sites a nightly change can trip)

| Site | Current pin | Trips when | Action |
|---|---|---|---|
| `ci.yml` ~:51 | `skipped == 2` | Step 5's live-Redis contract file lands (skips without a Redis endpoint) | conscious re-baseline `2 → 2+N`, comment names **both** parity suites |
| `verify-egress-blocked.sh` ~:131 | `--expect-pass 10 --expect-skip 1` | Step 7's s11 single-node variant lands (skip becomes assertion) | re-baseline `→ 11+0` across **every** site enumerated in Step 7 (the flip also lives in script hints, the attestation, the harness README, its unit twin, CLAUDE.md, and MULTI_CLOUD.md — cold-review F5), same commit |
| `scripts/ops_cp_splitbrain/README.md` ~:60 | dev gate `--expect-pass 11 --expect-skip 0` | **untouched this arc** — 3-node topology still executes classic s11 | assert unchanged; drift = STOP |
| `scripts/graph_eval` tallies + `max_wall_s` ceilings | smoke `5` / full `20` / laptop-calibrated ceilings | Step 4's CI wall-profile calibration | conscious calibration commit, inline comment; set composition + judge identity untouched |

---

## Resolved question (a) — runner fit: **GH-hosted until measurement says otherwise**

The entire recorded prior is one line ([W2_OPENER.md](W2_OPENER.md) ~:186): "GH-hosted
disk ~14 GB vs image set; self-hosted fallback if it doesn't fit." Resolution is **by
measurement**: Step 1's probe prints `df -h` before/after each leg,
`docker image inspect` sizes, and per-leg wall clocks on real runner hardware
(ubuntu-latest, 4 vCPU / 16 GB / ~14 GB free disk). Priors that suggest it fits: the
offline bundle tar measures ~450 MB on disk; separate jobs get separate fresh runners,
so fit is **per-job, never summed**; laptop walls (17–20 min harness, ~20 min offline
chain) were measured on a 4 GB WSL2 VM — runner hardware is stronger everywhere except
possibly LLM inference.

**Security caution (plan-review finding, recorded so "self-hosted" is never reached for
casually):** this repo is **public**, and GitHub explicitly warns against self-hosted
runners on public repositories — workflow runs from forks can execute arbitrary code on
the runner machine. If measurement forces the fallback conversation (eval smoke >
~45–60 min is the trigger — see (b)), the preference order is: **(1)** slim the nightly
eval to fewer/cheaper prompts; **(2)** a scheduled-only workflow that fork PRs can
never trigger; **(3)** a throwaway VPS as the runner — **never a machine on the home
network**. Escalate to Jesse with the measured numbers before any of the three.

## Resolved question (b) — eval wall ceilings on CI hardware: **probe, then calibrate**

The rubric `max_wall_s` ceilings and the smoke/full budgets are **laptop-calibrated**
(warm llama3.2, sequential behind the Ollama lock, "keep the laptop otherwise idle" —
[scripts/graph_eval/README.md](../scripts/graph_eval/README.md) §Budgets). A 4-vCPU
CPU-only runner is a different instrument: ceilings **will** trip spuriously if
inherited. Resolution: Step 1 runs smoke **ungated** (no `--expect-pass`, generous job
timeout) and records per-prompt walls; Step 4 then introduces an env-selected **CI wall
profile** as a conscious calibration commit (house inline re-baseline comment; judge
identity, threshold, and set composition untouched). Never a silent multiplier.

Two subordinate risks the probe also answers:
- **Search egress from runner IPs**: L3/L4 smoke prompts absorb live DuckDuckGo/Tavily
  latency; datacenter IPs are a known DDG rate-limit/captcha target. The flake protocol
  absorbs a transient miss (one re-run), not a systematic block. If the probe shows
  systematic search failure, the fallback is a `TAVILY_API_KEY` repo secret (API-based,
  datacenter-friendly) — flagged to Jesse before adding any secret.
- **Ollama install/pinning**: no marketplace action — install a **pinned Ollama release**
  (versioned download, recorded sha256) and cache `~/.ollama/models` via `actions/cache`
  keyed on model + Ollama version (~2 GB, inside the 10 GB cache quota). Run
  `ollama pull llama3.2` **unconditionally** — on a healthy cache it is a cheap
  digest-verify no-op, and it is the validation step that keeps a poisoned or
  partially-restored cache from producing a teaches-nothing blob-error red
  (cold-review F8). The harness self-asserts provider/model at startup and
  refuses to run zeroed — that assertion is the leg's own env guard.

## Resolved question (c) — trigger shape: **`schedule` + `workflow_dispatch`, nothing else**

Cron `17 3 * * *` (03:17 UTC — off-peak, odd minute; Jesse may re-pick at review) +
`workflow_dispatch` for on-demand re-runs. `concurrency: { group: nightly,
cancel-in-progress: false }` — a nightly must finish, not yield to the next one. Repo
is public → minutes are free; the budget question is dead.

**Rejected alternative (recorded so it isn't re-litigated):** the
[NEXT_STEPS_PLAN.md](NEXT_STEPS_PLAN.md) §Cross-cutting "nightly **or on
ops/graph-path changes**" trigger variant. A path-trigger would add 40–60 min latency
to every ops/graph PR to duplicate the local gate ladder that already guards those
paths pre-PR (harness + eval smoke/full are mandatory local gates). Revisit only if a
soak-period regression ever demonstrably slips the window between the local gate and
the nightly.

**Recorded risk:** GitHub disables `schedule` workflows after **60 days of repo
inactivity**. P4's code freeze (2–4 weeks) fits inside that window, but a longer quiet
period silently stops the nightly — and an absent run looks exactly like a green one
from the issues list. Filed in Follow-ups (heartbeat visibility) rather than solved
here.

## Resolved question (d) — failure visibility: **deduped auto-issue**

Scheduled-run reds attach to no PR; watcher e-mail is easy to miss. Each job (or one
`needs`-all reporter job) runs `if: failure()` → `gh issue list --label nightly-red`
→ comment on the open issue or create it. `GITHUB_TOKEN` with `issues: write`;
first-party `gh` only. **Approved in advance (2026-07-29, Jesse, plan review)** —
ratified by this PR's merge.

## Resolved question (e) — s11 single-node variant: **severable stretch (Step 7)**

[PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P1 labels it stretch; it stays severable — if
the execution session runs long it drops to Follow-ups **without ceremony**, and the
interlock table documents the `10+1 → 11+0` flip at both ends either way, which is
what makes dropping it safe. Design (from the W1.5 filing,
[W2_OPENER.md](W2_OPENER.md) ~:187-188): on `<3` etcd members
([s11's topology gate](../scripts/ops_cp_splitbrain/scenarios/s11_kill_etcd_leader_storm.py)
~:43), instead of the explicit SKIP, run the single-node assertion — SIGKILL the sole
etcd → **sustained 503s on durable writes are the correct behavior** (no survivor to
resume on) → restart etcd → durable writes resume within bound. Classic s11 on ≥3
members is untouched, so the dev gate stays `11+0`.

## Resolved question (f) — `OPS_FENCE_AUTHORITY=redis` legacy pass: **out**

**Rejected alternative (recorded):** a second nightly split-brain pass under redis
authority. It is the pure opt-in rollback backend — retained, not defaulted, with its
own recorded unelectability quirks under s07/s08b
([scripts/ops_cp_splitbrain/README.md](../scripts/ops_cp_splitbrain/README.md) ~:35-38).
A nightly leg would spend ~20 min/night certifying a mode the product does not run.
Revisit only if the rollback path is ever exercised in anger.

## Resolved question (g) — checkpoint residual (PR #16): **three pieces, three fates**

The residual ([PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P1: "unit-tested + one manual live
smoke, which is the manual-discipline state CI exists to end") splits:

1. **Live-Redis checkpointer coverage → per-push `redis-parity` job (Step 5).** The
   seam was designed for exactly this:
   [tests/test_checkpoint_saver.py](../tests/test_checkpoint_saver.py) ~:3-6 — "the
   shared assertion body `_assert_checkpointer_contract` is the anchor — a future
   live-Redis CI leg runs the same body against a real binary client." Mirrors the
   `etcd-parity` job pattern exactly ([ci.yml](../.github/workflows/ci.yml) ~:70-132:
   service container, env-gated test file, junit `skipped == 0` non-vacuity assert).
   **The live leg also carries the resume battery** (cold-review F1's resolution):
   [tests/test_checkpoint_resume.py](../tests/test_checkpoint_resume.py) reaches
   Redis only through the patched binary factories (~:80-85), so the live variant
   swaps real binary clients through the same seam and drives the **real Pregel
   interrupt→resume loop against real Redis, no LLM anywhere** — that, not a fake,
   is what "flag-on checkpoint leg in CI" honestly means at unit-infra level. If
   fixture parametrization resists in-session, the saver contract is the floor and
   the resume-live delta is filed loudly, never silently. Per-push, not nightly —
   it is seconds-cheap, and burying a per-push-worthy signal in nightly would
   repeat the exact rot pattern this phase ends. **Approved in advance (2026-07-29,
   Jesse, plan review)** as a deliberate extension beyond "nightly tier" literally;
   required-checks membership per settled decision 2.
2. **Flag-on eval smoke — rejected as vacuous by construction (cold-review F1,
   recorded so it isn't re-litigated).** The draft plan had a `nightly-eval` matrix
   entry with `GRAPH_CHECKPOINTING_ENABLED=true`
   ([app/core/config.py](../app/core/config.py) ~:104). The cold review killed it:
   the eval harness imports the **bare `compiled_graph`** and streams it directly
   (`scripts/graph_eval/runner.py` ~:16/:56), and doctrine pins that singleton
   checkpointer-free forever ([CLAUDE.md](../CLAUDE.md) §Checkpointing) — the
   checkpointed twin exists only behind `get_checkpointed_graph()` on the worker
   path. A flag-on eval entry runs byte-identical code to flag-off: green certifies
   nothing, which is precisely the vacuity class P1 exists to end. Making the
   harness flag-sensitive would give it a Redis dependency and break its zero-infra
   doctrine — rejected. The flag-on coverage lives in piece 1 (the checkpoint/resume
   machinery over real Redis) and piece 3 (the worker path end-to-end, manual —
   cold-review F15's distinction: piece 1 never touches `get_checkpointed_graph()`).
3. **The manual interrupt→resume live smoke stays manual.** It is the only check
   that exercises the worker path end-to-end (`get_checkpointed_graph()`, durability
   `"sync"`, WS resume) with a live LLM — it caught P0.1/C7 pre-PR — and automating
   it means driving session control over a live WebSocket mid-run: a real harness
   build, out of P1's 1–2-session scope. Filed in Follow-ups (P3-adjacent). Stated
   here so nobody reads P1 as having automated it.

---

## Leg designs (grounded in code)

### `nightly-splitbrain`

Full dev-parity stack on the runner — the first compose-based job in this CI (risk
priced into Step 1). Sequence:

```yaml
# token single-sourcing: kills the drift trap by construction
- TOKEN=$(openssl rand -hex 16); echo "OPS_ADMIN_TOKEN=$TOKEN" >> .env
  echo "OPS_ADMIN_TOKEN=$TOKEN" >> "$GITHUB_ENV"
- docker compose -f docker-compose.yml -f docker-compose.ops-ha.yml \
    -f docker-compose.ops-obs.yml -p tess-engine up --build -d   # FULL first-run up
- python -m scripts.ops_cp_splitbrain run-all --expect-pass 11 --expect-skip 0
  # env: OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml, OPS_HA_CONVERGENCE_TIMEOUT=<probed>
- if: failure() → upload `docker compose logs` artifact
```

The explicit **full** first `up` (worker + otel-collector included) is
belt-and-suspenders plus wall-clock placement, not a correctness crutch — the
`reset_stack` torn-down hazard was already fixed in code
([scripts/ops_cp_splitbrain/harness.py](../scripts/ops_cp_splitbrain/harness.py)
~:48-56, worker-sentinel → full `compose_up`; cold-review F7 — Step 8 strikes the
stale [NEXT_STEPS_PLAN.md](NEXT_STEPS_PLAN.md) ~:191-195 filing). The explicit `up`
front-loads image build cost outside the harness's timing and guarantees the obs
overlay is in the running stack, which s10 needs to pass (it FAILs, never skips,
without it). Convergence timeout starts at 60 s (the 4 GB-VM measurement) and is
re-pinned from the probe. Wall estimate: 17–20 min run-all + compose build/up ≈
25–35 min; `timeout-minutes: 60` initial.

**Planted violation (two layers):** (1) *product-level* — one run on a fresh runner
with the obs overlay withheld from **both** the compose `up` file list and
`OPS_HA_COMPOSE_OBS` (cold-review F3: withholding only the env var leaves the obs
services running from the `up`, and s10's worker-metrics red path never fires) → s10
FAILs on its own worker-metrics/collector assertions (s10 has no `skip_reason`;
observability loss is a red, never a skip) → job red; (2) *tally-wiring* — one run
with `--expect-pass 10` → the harness's own `EXPECTATION FAILED` exit flips the job
red, proving the gate reaches job status. Salient lines from both pasted into the PR
body.

### `nightly-offline`

Three sequential steps, all scripts already `set -euo pipefail`:

```yaml
- actions/setup-node@v4 with node 22      # build-bundle runs `npm ci && npm run build`
                                          # on the HOST — pin node to ci.yml's frontend
                                          # job, or the leg reds on version drift (F6)
- deploy/offline/build-bundle.sh          # ~4 min laptop
- extract bundle → its install-offline.sh # ~2-3 min
- deploy/offline/verify-egress-blocked.sh # ~13 min; exits with the harness RC
```

The verifier's own `exit "$RC"` (baked-in `--expect-pass 10 --expect-skip 1` at ~:131)
IS the gate — the job adds nothing on top except `df -h` probes before/after
(runner-fit evidence) and a failure-logs artifact. Fresh runner per job means the
laptop's "one stack at a time" constraint (dev and offline share the compose project
name) does not apply — `nightly-splitbrain` and `nightly-offline` run on different
machines. `timeout-minutes: 45` initial.

**Planted violation:** corrupt a MANIFEST-covered file **inside the extracted
bundle** (e.g. one byte of `images/all-images.tar`) between extraction and install →
`install-offline.sh`'s `sha256sum -c MANIFEST.sha256` gate (~:38) is provably the
line that dies → job red → revert. (Cold-review F4: tampering the outer `.tar.gz`
reds in `tar -xzf`'s gzip CRC instead — a death that never reaches, so never proves,
the manifest gate.)

**Pre-assigned risk:** `MAX_APP_IMAGE_GB=3` was tuned against the laptop's containerd
**content** size (~255 MB vs ~1.14 GB unpacked — [W2_OPENER.md](W2_OPENER.md)
~:209-211); GH runners use the classic overlay2 store where
`docker image inspect .Size` reports a different quantity. If the probe trips the
ceiling: **raise it with the house inline comment** and file an image-diet follow-up —
never delete the guard.

### `nightly-eval`

```yaml
- install pinned Ollama release (recorded sha256) + actions/cache on ~/.ollama/models
- ollama serve & + readiness wait; ollama pull llama3.2   # no-op on cache hit
- write .env: DEFAULT_LLM_PROVIDER=ollama, OLLAMA_BASE_URL=http://localhost:11434
- python -m scripts.graph_eval run-all --set smoke --expect-pass 5
```

No checkpointing matrix — the flag-on eval entry was killed as vacuous by
construction (resolved question (g)2, cold-review F1); this leg certifies the bare
product chain on CI hardware, nothing else.

The harness self-asserts resolved provider/model at startup and refuses zeroed-metrics
runs — the leg inherits that guard. The full-20 set does **not** ride nightly yet
(staged in Follow-ups until the CI smoke wall is known). Honesty line restated from
[scripts/graph_eval/README.md](../scripts/graph_eval/README.md) §Scoring: the 3B local
judge scores fluent wrong-lens answers 8–9 — **routing regressions are caught by the
structural layer; the judge gates answer quality.** This leg's claim is "the chain
still produces structurally sound, judge-acceptable answers on CI hardware," nothing
stronger. `timeout-minutes: 60` initial (CPU-only inference is the arc's biggest
unknown; see (a)/(b) escalation thresholds).

**Planted violation:** the W2-S2 sabotage idiom, re-run on the runner — a temporary
commit forcing a wrong routing override in
[app/graph/routing.py](../app/graph/routing.py) → structural agent-expectation
failures → job red → **reverted in the immediately following commit** (settled
decision 5's carve-out; the pair is the evidence).

### `redis-parity` (per-push, in `ci.yml` — Step 5)

Clone of the `etcd-parity` job shape: `redis:7-alpine` service container (this image
has a shell — a `redis-cli ping` health check or an explicit wait step both work; keep
the explicit wait step for symmetry with the etcd job and its distroless lesson,
[ci.yml](../.github/workflows/ci.yml) ~:90-93); new env-gated test file (e.g.
`tests/test_checkpoint_saver_live.py`, gated on `OPS_TEST_REDIS_URL`) that runs the
shared `_assert_checkpointer_contract` body **and the resume battery** (via the
binary-factory seam — resolved question (g)1) against a **real binary client** — the
binary-factory rule holds ([CLAUDE.md](../CLAUDE.md): never `decode_responses=True`;
UTF-8-decoding msgpack corrupts silently); junit assert copied from ~:116-132
(`tests >= N, skipped == 0`, plus the module's endpoint-gate import). Consequences:
plain `pytest tests/` now skips N more → `ci.yml` ~:51 re-baselined `2 → 2+N`, comment
updated to name **both** parity suites; and
[tests/test_checkpoint_saver.py](../tests/test_checkpoint_saver.py) ~:5-6's docstring
("No skips added … exactly 2") goes stale → updated in the same change (cold-review
F12).

### s11 single-node variant (stretch — Step 7)

Touches `scripts/ops_cp_splitbrain/**` → carries the harness-change discipline (see
House rules). Assertion design in (e); its planted violation: sabotage the variant by
skipping the etcd restart → the "durable writes resume" assertion must time out red.

### Cross-leg conventions

`defaults: { run: { shell: bash } }` (settled decision 8); `permissions: { contents:
read, issues: write }`; `concurrency: nightly`; every leg uploads diagnostics as
artifacts on failure; no marketplace actions; every `timeout-minutes` and every
numeric pin carries the house inline re-baseline comment naming its probe measurement.

---

## Steps (proposed commits)

### Step 1 — Scaffold + measurement probe (measure-before-pin)

- New `.github/workflows/nightly.yml`: all three nightly jobs **ungated** (no
  `--expect-*` on splitbrain/eval; the offline verifier's baked-in tally stays — it is
  the leg), probe-phase `timeout-minutes` near the 360-min job maximum (cold-review
  F14: a guessed probe ceiling could kill the measurement run before it yields the
  numbers it exists to produce — CPU-only inference is the unknown being measured),
  `df -h` + `docker image inspect` + per-leg wall
  printing. **Temporary trigger**: `on: push: branches: [ops/p1-nightly-ci]` plus a
  job-level `if: contains(github.event.head_commit.message, '[run-nightly]')` opt-in —
  `workflow_dispatch` cannot fire for a workflow absent from the default branch
  (confirmed at plan review), and the opt-in keeps iteration pushes from burning
  60-min runs. Marked with a comment: flipped to schedule in Step 6.
- Push with `[run-nightly]`; collect: per-leg walls, disk before/after, image inspect
  sizes, eval per-prompt walls, search reachability, convergence timing.
- **Verify:** probe run green-or-diagnosed; every number recorded in the PR body —
  these resolve questions (a)/(b) and set every pin in Steps 2–4.

### Step 2 — Split-brain leg armed + non-vacuity

- Pin `--expect-pass 11 --expect-skip 0`, probed `OPS_HA_CONVERGENCE_TIMEOUT`,
  `timeout-minutes`; token single-sourcing; failure-logs artifact.
- **Red-first:** the two planted violations from the leg design (obs-overlay withheld
  → s10 red; `--expect-pass 10` → expectation-failed red), salient lines pasted into
  the PR body, then reverted.
- **Verify:** a full green `[run-nightly]` run with the 11/11 tally visible in the log.

### Step 3 — Offline leg armed + non-vacuity

- Gate on the verifier's exit; artifacts; `MAX_APP_IMAGE_GB` re-tuned **only if** the
  probe tripped it (inline comment naming the overlay2 number).
- **Red-first:** bundle-tamper sabotage → manifest-sha death, lines pasted, reverted.
- **Verify:** green run with the attestation text in the job log.

### Step 4 — Eval leg armed + CI ceiling calibration + non-vacuity

- CI wall profile introduced as a conscious calibration commit (inline comment citing
  Step 1's per-prompt walls; judge identity/threshold/set untouched); gate
  `run-all --set smoke --expect-pass 5`. No checkpointing matrix ((g)2, cold-review
  F1).
- **Red-first:** routing-override sabotage commit → structural reds on the runner,
  lines pasted, **reverted in the immediately following commit** (carve-out). The
  sabotage push must itself carry `[run-nightly]` or the nightly red never happens;
  the PR's per-push `ci.yml` run will also go red on routing unit tests — expected
  noise, and the pasted evidence must come from the **nightly** run (cold-review
  F11).
- **Verify:** green run(s); per-prompt walls within the new profile.

### Step 5 — `redis-parity` job + unit-tally re-baseline (the one `ci.yml` touch)

- New `tests/test_checkpoint_saver_live.py` (env-gated, real binary client, shared
  contract body + the resume battery via the binary-factory seam — (g)1; if the
  resume fixtures resist parametrization, ship the contract floor and file the delta
  loudly); `redis-parity` job cloned from the `etcd-parity` template; `ci.yml`
  ~:51 re-baselined `2 → 2+N` naming both parity suites; the
  `test_checkpoint_saver.py` ~:5-6 docstring updated in the same change (F12).
- **Red-first (vacuity detection proven):** run the junit assert **without** the Redis
  endpoint → the new tests skip → `skipped == 0` assert fails loudly. Then green with
  the service container.
- **Verify:** per-push CI green on the PR itself (this job, unlike the nightly legs,
  runs right there). Jesse-step filed: required-checks membership after a few days
  green (settled decision 2).

### Step 6 — Trigger flip + failure visibility

- Remove the push trigger and `[run-nightly]` opt-in; add `schedule` (cron
  `17 3 * * *`) + `workflow_dispatch`; add the deduped `nightly-red` issue reporter
  (`if: failure()`, `gh` + `GITHUB_TOKEN`); `permissions: { contents: read, issues:
  write }`. **Deliberately last** — after this commit the workflow cannot run
  pre-merge, so every proof precedes it.
- **Verify:** YAML review (run `actionlint` if available); all evidence already in the
  PR body; the first post-merge `workflow_dispatch` run is a filed follow-up, not a
  claim of this PR.

### Step 7 (stretch, severable) — s11 single-node variant

- Variant assertion per (e); the `10+1 → 11+0` flip lands at **every** site in one
  commit (cold-review F5 — the 10+1 claim lives in more prose than the invocation
  line, which is exactly how W1.5's stale-tally rot started):
  `verify-egress-blocked.sh` ~:8 (header), ~:131 (invocation), ~:154 (attestation
  body); `install-offline.sh` ~:123 ("next:" hint — the site W1.5 already had to
  kill stale text in once); `build-bundle.sh` ~:165 (same hint);
  [scripts/ops_cp_splitbrain/README.md](../scripts/ops_cp_splitbrain/README.md)
  (§Topology skips + the tally paragraph); `tests/test_splitbrain_topology_gate.py`
  (the unit twin); [CLAUDE.md](../CLAUDE.md) ~:53-54 (offline-deploy paragraph);
  [deploy/MULTI_CLOUD.md](../deploy/MULTI_CLOUD.md) ~:273-278 + ~:333 (Sovereignty
  Audit / runbook).
- Harness-change discipline: local dev `run-all` (11/11) + offline verifier chain
  re-run green before the commit.
- **Red-first:** skip-the-restart sabotage → resume assertion times out red; revert.
- **Verify:** offline leg green at the new `11+0` tally. If the session runs long:
  this whole step moves to Follow-ups, nothing else changes.

### Step 8 — Docs flip

- [PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P1 `⬜ → ✅` with one-line mechanism + the
  sabotage-evidence pointers — **one per planted violation, count matching the
  landed steps: five without Step 7, six with it** (cold-review F9; salient lines
  live in the PR body per settled decision 4); [W2_OPENER.md](W2_OPENER.md)
  §Session 3 runway marked landed; [NEXT_STEPS_PLAN.md](NEXT_STEPS_PLAN.md) §W1.5
  durable-cure marked delivered, §Cross-cutting — CI updated, and the `reset_stack`
  hazard filing (~:191-195) **struck** — already verified at authoring (cold-review
  F7): `harness.py` ~:48-56 grew the worker-sentinel `compose_up` fallback and
  NEXT_STEPS_PLAN ~:141-142 records it proven; only the filing text is stale;
  [CLAUDE.md](../CLAUDE.md) per-push-CI convention line + file-pointer table gain
  `nightly.yml` and `redis-parity`.
- **Verify:** `python -m scripts.check_doc_links` → 0 broken; `pytest tests/ -q`
  green at the re-baselined tally; PR into main, merge left to Jesse.

---

## House rules (unchanged)

Every leg gets its planted-violation red **before** its green is trusted, with the
salient failure lines recorded in the PR body (URLs are pointers, not evidence —
settled decision 4); a harness failure is a product bug until proven otherwise — fix
the product, never soften the assertion; tallies/pins are executable claims with the
house inline re-baseline comment; suite + doc-links green per commit; PR into main,
merge left to Jesse. **Scope fence:** no `app/**` changes this arc **except**
planted-violation commits under settled decision 5's carve-out (transient, reverted in
the immediately following commit, the pair is the evidence — no ops battery or eval
gate is triggered by a same-commit-reverted sabotage pair, but the sabotage runs
themselves ARE the gate evidence); Step 7 touches `scripts/ops_cp_splitbrain/**` and
carries the harness-change discipline (dev `run-all` + offline chain re-run before
commit); golden-set composition, judge identity, and all `app/graph/**` behavior are
out of scope.

## Environment notes

- **Token drift** (the 403 storm): compose interpolates `OPS_ADMIN_TOKEN` from `.env`;
  the harness reads shell env. Locally: export before `run-all`
  ([scripts/ops_cp_splitbrain/README.md](../scripts/ops_cp_splitbrain/README.md)
  ~:11-16). In CI: single-source one generated token into both (leg design).
- **s10 needs the obs overlay** (`docker-compose.ops-obs.yml` + `OPS_HA_COMPOSE_OBS`)
  or it FAILs — never skips. Worker metrics assume `--concurrency=1` (deploy
  convention).
- **Stale etcd volumes** (old raft term) + build contention → health-check timeouts:
  `docker compose down -v` for a fresh cluster before local re-runs. Fresh runners are
  immune.
- **Pipes mask exit codes**: in CI, settled decision 8 (`shell: bash` ⇒ pipefail); on
  this laptop (PS 5.1), check the command's own status, not the pipeline tail's.
- **containerd vs overlay2**: `docker image inspect .Size` measures different
  quantities on the laptop (content, ~255 MB) vs GH runners (overlay2) — never compare
  the two; the ceiling is tuned per-instrument (leg (b) risk).
- **Distroless service containers**: no `--health-cmd` on images without `/bin/sh`
  (etcd lesson, [ci.yml](../.github/workflows/ci.yml) ~:90-93); `redis:7-alpine` has a
  shell, but keep the explicit wait step for symmetry.
- **Scheduled workflows auto-disable after 60 days of repo inactivity** — see (c)'s
  recorded risk.
- PS 5.1 quote-mangling: commit/PR bodies via `git commit -F` / `--body-file`; `gh` at
  `C:\Program Files\GitHub CLI\gh.exe`.
- Windows CPython <3.13 `time.time()` ticks ~15.6 ms — if any new test stamps times,
  patch the stamps; never assert real-clock distinctness.

## Follow-ups filed

- **Full-20 eval set nightly** — once the CI smoke wall is measured and the full-set
  extrapolation fits the window; until then full stays a local pre-PR gate.
- **Manual interrupt→resume live smoke automation** — needs a WS session-control
  driver; P3-adjacent (chaos harness territory), explicitly not delivered by P1.
- **First post-merge scheduled/dispatch run verified green** — next-morning check +
  an immediate `workflow_dispatch` after merge; the PR itself cannot prove the
  schedule fires.
- **`redis-parity` → required checks** — Jesse-step after its first few days green
  (settled decision 2).
- **Nightly heartbeat visibility** — an absent run is invisible in the issues list
  (60-day auto-disable, runner outages); decide in P3 whether "nightly ran today"
  needs its own check or the Actions UI suffices.
- **s11 single-node variant** — lands here only if Step 7 was dropped.
- **Image diet** — only if the probe trips `MAX_APP_IMAGE_GB` on overlay2; the ceiling
  is raised with a comment first, shrunk later.
- **`TAVILY_API_KEY` secret** — only if the probe shows systematic DDG blocking from
  runner IPs (question (b)); adding any secret is a Jesse-step.
