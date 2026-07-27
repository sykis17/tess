# W2 — Chain Instrumentation + Eval Harness + CI — Opener (resume here)

Cold-start doc for **W2** of the [Next-Steps Program](NEXT_STEPS_PLAN.md): give the product
graph what the ops plane already has — per-node observability — plus a repeatable eval gate
and the CI ladder (which today does not exist: there is **no `.github/`**). Nothing
downstream (W5, W6) is verifiable without this measurement foundation.

Filing: [NEXT_STEPS_PLAN.md §W2](NEXT_STEPS_PLAN.md) + §Cross-cutting — CI. Session-local
facts (laptop profile, measured runtimes, W1.5 tooling) were folded in from
[W2_HANDOFF_NOTES.md](W2_HANDOFF_NOTES.md) (now historical). W1.5 evidence: PR #12
(`ops/w1.5-offline-verifier`, merge `cf05540`).

---

## Start state (verified 2026-07-27)

1. **PR #12 merged** — main at `cf05540`, clean tree. W2 Session 1 branch:
   `ops/w2-graph-observability`.
2. `python -m pytest tests/ -q` → **289 passed, 2 skipped** (the 2 = live-etcd parity tests,
   env-gated). `python -m scripts.check_doc_links` → **0 broken** (487 links).
3. **No CI exists** — no `.github/`, no workflow files. The four manual gates (unit, parity,
   split-brain, doc-links) run by hand.
4. The product graph has **zero** instrumentation: no OTel calls in `app/graph/`,
   `app/agents/`, `app/llm/`; token counts are not surfaced anywhere (both LLM providers
   discard usage metadata; `stream()` yields plain `str`).
5. Docker notes: the offline stack auto-revives after reboot (`restart: unless-stopped`) —
   check `docker ps` before assuming a clean slate; `docker info` must show non-zero CPUs
   (else engine wedge → restart Docker Desktop / `wsl --shutdown`, re-run the whole gate,
   never half-count).

---

## Settled decisions (locked with Jesse, 2026-07-27)

1. **Run-history sink: sqlite** — the eval harness (S2) persists per-run history
   (scores, tokens, latency, cost) to a sqlite file under `scripts/graph_eval/`,
   **gitignored AND dockerignored in the same commit** (the W1.5 bundle-bloat lesson,
   inherited not rediscovered). Live spans/metrics go to the existing otel-collector.
2. **Eval scoring: both** — deterministic rubric checks carry the per-push signal; the LLM
   judge runs nightly via the existing `create_llm()` factory, **defaulting to Ollama-local
   (zero spend)**, provider as a config knob (flip to Gemini for rubric quality later).
3. **Golden set: ~15–25 hand-authored** prompts spanning L0–L4 × product modes (POV vs tool
   vs media).
4. **Arc staging:** S1 = instrumentation + guard twin + cheap per-push CI; S2 = eval
   harness; S3 = nightly docker legs (split-brain, offline chain, eval judge).
5. **Duration-histogram outcome policy** (sign-off design rule): duration histograms record
   **only when outcome=success** — interrupted/errored/cancelled runs are short by
   definition and would pollute latency trends in the flattering direction (W5's gate is
   "median latency drops"). No `outcome` label on histograms (cardinality); the counters
   carry the outcome split.

---

## Invariants (all sessions)

- **OFF by default.** `GRAPH_METRICS_ENABLED` / `GRAPH_TRACING_ENABLED` both default false;
  all four observability toggles off ⇒ product path behavior byte-identical. `record_*`
  helpers never raise.
- **Cardinality discipline** (same as ops): `tess_graph_` prefix; fixed label allowlist
  (`node, chain_profile, product_mode, outcome, provider, model, kind`); `session_id` /
  `panel_id` / URLs / error strings are **span attributes only, never metric labels**;
  unknown `chain_profile`/`product_mode` fold to `"other"`. Guard:
  `tests/test_graph_metrics.py` (the required twin of
  [tests/test_ops_metrics.py](../tests/test_ops_metrics.py)).
- **Never cross prefixes**: graph metrics never use `tess_ops_`, ops never `tess_graph_`.
  Ops' `BANNED_LABELS` bans `provider` because in ops-land it shadows unbounded multi-cloud
  provider records; the graph allowlist admits it **only** as the bounded `LLMProvider`
  enum (`ollama|gemini`), domain-tested.
- **Ops path untouched** unless a session deliberately takes on the heavy ladder:
  `app/ops/**`, `app/api/ops.py`, `scripts/ops_cp_splitbrain/**`,
  `docker-compose.ops-obs.yml`, `tests/test_ops_metrics.py`. S1 verified its `app/worker.py`
  edits sit outside the ops-task regions guarded by
  [tests/test_ops_fencing.py](../tests/test_ops_fencing.py).
- **Non-vacuous evidence for every new guard** — each gate names its red-first proof; tally
  asserts are exit-code artifacts, never log-greps.
- **Tests are unit-level, no docker, no live LLM.** No pytest-asyncio (absent from the
  hash-pinned lock — protecting the lock beats convenience): new async-shaped tests are sync
  functions driving coroutines via `asyncio.run(...)`.

---

## Session 1 — graph observability + guard twin + per-push CI

Five gated commits on `ops/w2-graph-observability`; full detail lived in the session plan,
condensed here to what a resume needs.

1. **docs** — this opener; decisions marked SETTLED in NEXT_STEPS_PLAN; handoff notes
   marked historical; `CP_HA_ENGINEERING_REPORT.md` archived under `docs/archive/ops/`
   (W1.5-filed follow-up).
2. **per-push CI** — `.github/workflows/ci.yml`, four jobs (names are stable API for branch
   protection): `unit` (lock-installed via `pip --require-hashes`, junit tally assert
   **skipped == 2** with the re-baseline comment inline), `doc-links`, `etcd-parity`
   (service container `quay.io/coreos/etcd:v3.5.32`, env-driven, localhost advertise URLs;
   `OPS_TEST_ETCD_ENDPOINT=http://127.0.0.1:2379`; junit assert **tests ≥ 4, skipped == 0**
   — exit code alone is vacuous since the suite is green with the etcd half skipped),
   `frontend` (`npm ci` + oxlint + `tsc -b`/vite build). Nightly legs are S3, in a separate
   `nightly.yml`.
3. **observability core** — `app/graph/observability.py` (metric objects, `_safe`
   never-raise recorders, node contextvar, `instrument_node` / `graph_run` / `llm_call`
   wrappers), `app/graph/model_costs.py` (module dict; unknown model → $0, which covers all
   Ollama/local models), config flags, and the guard twin **with an in-suite trip test**
   (a throwaway banned-label metric must trip the allowlist helper — the guard's own teeth
   under permanent test; the ops twin should eventually inherit this pattern — see
   §Follow-ups).
4. **token usage plumbing** — `app/llm/usage.py::extract_usage` (standardized
   `usage_metadata` → Ollama `response_metadata` fallback → `(None, None)`);
   `LLMResponse.prompt_tokens/completion_tokens` (S2's per-run token feed); both providers
   record via `llm_call` in `finally`. Cancellation mechanics, precisely: the consumer
   (`app/graph/stream_utils.py`) raises `SessionInterrupted` in **its own** loop — nothing
   is thrown into the provider generator; it is abandoned and gets `GeneratorExit` at
   asyncgen finalization, so recording may flush late (documented, acceptable). Tests that
   assert the cancelled path must `await agen.aclose()` explicitly — GC-driven finalization
   races otherwise.
5. **wiring + overlay + scope docs** — every `builder.add_node` routes through
   `instrument_node` (static guard test reads the builder source); `graph_run` wraps the
   worker's `astream` loop; `docker-compose.graph-obs.yml` is the self-contained
   verification overlay (the ops-obs file configures `web-standby`, which only exists under
   the HA overlay, and is harness-consumed — untouched); CLAUDE.md + MULTI_CLOUD.md scope
   text updated in the same commit.

**Metric inventory** (all `tess_graph_`-prefixed):

| Metric | Type | Labels |
|---|---|---|
| `runs` | Counter | chain_profile, product_mode, outcome |
| `run_duration_seconds` | Histogram (success only) | chain_profile, product_mode |
| `node_runs` | Counter | node, chain_profile, product_mode, outcome |
| `node_duration_seconds` | Histogram (success only) | node, chain_profile, product_mode |
| `llm_calls` | Counter | node, provider, model, outcome |
| `llm_duration_seconds` | Histogram (success only) | provider, model |
| `llm_tokens` | Counter | node, provider, model, kind (prompt\|completion) |
| `llm_cost_usd` | Counter | node, provider, model (only when > 0) |

`agent` folds into `node` (specialist node name == agent name). Spans: `graph.run`
(session_id/chain_profile/product_mode/outcome), `graph.node` (+node/agent), `graph.llm`
(+provider/model/tokens/cost/streaming/outcome). Graph runs only in the Celery worker;
exposition rides the existing `:9109` worker port (same `--concurrency=1` prefork
assumption as ops — see `deploy/MULTI_CLOUD.md` §Observability).

### Session 1 verification

```bash
# per-commit
python -m pytest tests/ -q                      # expect ~315-320 passed, 2 skipped by S1 end
python -m scripts.check_doc_links               # 0 broken

# e2e (commit 5 gate): flags-on stack, one L0 turn, then flags-off proof
docker compose -f docker-compose.yml -f docker-compose.graph-obs.yml -p tess-engine up --build -d
# WS client MUST send the JSON envelope {"text": "...", "chain_profile": "L0"} —
# plain text always resolves to L4 (app/core/ws_payload.py)
curl -s 127.0.0.1:9109/metrics | grep '^tess_graph_'   # run/node/llm series, llm_tokens > 0
# spans: docker compose cp from otel-collector, look for graph.run/graph.node/graph.llm
# then recreate WITHOUT the overlay, one turn → zero tess_graph_ anywhere
```

CI proof: all four jobs green on the introducing PR; non-vacuity = one WIP push with the
parity env line removed → parity job red on the skipped==0 assert (recorded, dropped).
**Heavy ladder not triggered** — no ops-path files change.

---

## Session 2 runway — eval harness (`scripts/graph_eval/`)

> **Session opener written:** [W2_S2_OPENER.md](W2_S2_OPENER.md) — invocation path
> verified in-process (zero infra), flake policy, wall-time budgeting, history schema,
> commit map. Start Session 2 there; the bullets below are the original runway sketch.

- Golden set 15–25 hand-authored prompts × rubric (L0–L4 × product modes), analogous in
  spirit to `scripts/ops_cp_splitbrain/`; `python -m scripts.graph_eval run-all` prints
  per-prompt scores + a tokens/latency/cost table (fed by `LLMResponse.prompt_tokens/
  completion_tokens` from S1 commit 4).
- Deterministic checks (structure: expected panels, POV counts, format, latency/cost
  ceilings) + LLM judge via `create_llm()`, default Ollama-local; judge provider/model is
  config. sqlite history file: **gitignored + dockerignored in the same commit**.
- **Non-vacuity gate:** the harness must catch a known regression — force a bad routing
  override, confirm the score drops. A rubric that always passes is vacuous.
- Cheap-harness-test pattern to copy: `tests/test_splitbrain_topology_gate.py` (argparse →
  exit-code wiring with docker patched out).

## Session 3 runway — `nightly.yml`

- Legs: split-brain harness (dev topology, `run-all --expect-pass 11 --expect-skip 0`),
  offline chain (`build-bundle → install-offline → verify-egress-blocked`, ~20 min
  measured), eval judge (budget: judge nightly only, deterministic per-push).
- Decide then: §Cross-cutting's "nightly **or on ops/graph-path changes**" trigger variant;
  runner fit (GH-hosted disk ~14 GB vs image set; self-hosted fallback if it doesn't fit).
- Stretch: **s11 single-node variant** (topology skip → assertion: sole etcd down →
  sustained 503s, durable writes resume after restart).
- Offline-chain re-baseline site when scenarios change:
  `deploy/offline/verify-egress-blocked.sh` (`--expect-pass 10 --expect-skip 1`, commented).

---

## Environment notes (this laptop, folded from the handoff notes)

- WSL2 capped `memory=4GB swap=4GB` (`.wslconfig`); ~100 GB free on C: if a CI-style
  parallel run needs the cap raised. **One stack at a time** — dev and offline share compose
  project `tess-engine`.
- Measured wall-clock for CI budgeting: offline chain ~20 min total (build ~4, install
  ~2–3, verify ~13); dev `run-all` from torn-down ~17–20 min; full pytest ~7 s.
- `gh` at `C:\Program Files\GitHub CLI\gh.exe` (not on PATH). House merge style: merge
  commits, merge left to Jesse.
- PowerShell 5.1 mangles embedded double quotes in native-command args (git parses message
  fragments as pathspecs and the commit **silently no-ops**) — write commit/PR bodies to a
  file: `git commit -F`, `gh pr create --body-file`.
- Git-Bash docker mounts need `MSYS_NO_PATHCONV=1` + `cygpath -w` for `-v` paths. The
  offline harness runner mounts the install dir at `/work` — mount the repo instead to
  iterate on harness code against a live offline stack without rebuilding the bundle.
- `build-bundle.sh` size ceiling reads `docker image inspect -f '{{.Size}}'`, which on this
  engine (containerd store) is **content** size (~255 MB), not the ~1.14 GB unpacked
  `docker images` number — tune `MAX_APP_IMAGE_GB` against the inspect number.

## Follow-ups filed

- **Ops twin inherits the in-suite trip test** (sign-off note): port
  `tests/test_graph_metrics.py`'s banned-label trip test to `tests/test_ops_metrics.py` in
  some later ops-path session (touching that file alone doesn't trigger the heavy ladder,
  but bundle it with real ops work anyway).
- **Post-merge Jesse-step (S1):** enable required checks on `main` for the four CI job
  names (`unit`, `doc-links`, `etcd-parity`, `frontend`) — the moment per-push CI becomes
  enforcement rather than information.
- **S3 stretch:** s11 single-node variant (above).
