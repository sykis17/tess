# W2 Session 2 — Eval Harness (`scripts/graph_eval/`) — Opener (resume here)

Cold-start doc for **W2 Session 2**: the repeatable eval gate for the product graph — a
versioned golden set scored by deterministic rubrics + an LLM judge, with per-run history
in sqlite. This is the second half of the W2 measurement foundation
([W2_OPENER.md](W2_OPENER.md) is the arc opener; S1 landed graph
observability + per-push CI as PR #13). Nothing in W5/W6 is landable without this gate.

Filing: [NEXT_STEPS_PLAN.md §W2](NEXT_STEPS_PLAN.md). All decisions are settled; the
open questions from the S1 kickoff brief are **resolved below, grounded in code** —
file:line references were verified 2026-07-27, at PR #13's head.

---

## Start state (verify first)

1. **PR #13 must be merged first** (`ops/w2-graph-observability` — this opener rides it
   as the final commit, the same way the W2 handoff notes rode PR #12). All four required
   checks are green and branch protection is already enforcing them on `main`.
   `git checkout main && git pull`, confirm the merge, then
   `git switch -c ops/w2-s2-graph-eval`.
2. `python -m pytest tests/ -q` → **325 passed, 2 skipped**.
   `python -m scripts.check_doc_links` → **0 broken** (~500 links).
3. **No docker needed this session** (see §Invocation). Ollama up on the host with
   `llama3.2` (`curl localhost:11434/api/tags`).
4. **Provider sanity on the host** (not in a container): confirm
   `python -c "from app.core.config import settings; print(settings.default_llm_provider, settings.ollama_base_url)"`
   resolves to **ollama** + a host-reachable URL. The compose files inject these env vars
   into containers; on the host they come from `.env` — if `.env` says gemini or a
   `host.docker.internal` URL that doesn't resolve, fix the env before measuring anything.
   The harness must **assert and record** the resolved provider/model at startup — graph
   model identity is part of the measurement, same as judge identity.
5. `docker ps` — nothing should be running; the offline stack auto-revives after reboots.

---

## Settled decisions + attached requirements (from the S1 sign-off + kickoff brief)

1. **sqlite history** at `scripts/graph_eval/history.db` — **gitignored AND dockerignored
   in the same commit that creates the writer** (the W1.5 bundle-bloat lesson).
2. **Scoring = both**: deterministic rubrics (strict) + LLM judge via `create_llm()`
   defaulting **Ollama-local** (zero spend), provider/model as config.
3. **Judge identity is part of the measurement**: judge provider + model + judge-prompt
   version pinned in config AND recorded in every history row. Golden set is versioned;
   the set version is recorded per run; set edits are deliberate re-baseline events with
   the house inline comment.
4. **Golden set ~15–25 hand-authored**, spanning L0–L4 × product modes, with
   **escalation-requiring prompts tagged** (`escalation-required`, ≥3 — W5's future gate
   depends on them existing).
5. **Non-vacuity before trust**: a forced bad routing override must drop the score
   (red-first, recorded) before the harness gates anything.

---

## Resolved question (a) — invocation path: **in-process, zero infra** (verified)

The harness drives the compiled graph directly:

```python
from app.graph import compiled_graph            # noqa: import AFTER env setup (below)
from app.graph.state import build_initial_state
state = build_initial_state(prompt, chain_profile=..., product_mode=..., session_id="")
async for update in compiled_graph.astream(state, stream_mode="updates"): ...
```

With `session_id=""` every transport side-effect is verifiably inert — no Redis, no
worker, no docker:

- `publish_panel` early-returns on empty session_id
  ([app/graph/panel_stream.py:9-10](../app/graph/panel_stream.py)).
- Specialists build a streaming panel **only when session_id is set**
  ([app/agents/base.py:54-56](../app/agents/base.py)); otherwise they take the plain
  `generate` path (base.py:95-97).
- `direct_responder` always streams
  ([app/graph/nodes/direct_responder.py:62](../app/graph/nodes/direct_responder.py)),
  but the per-chunk interrupt poll returns False **without touching Redis** when
  session_id is empty ([app/core/session_control.py:92-93](../app/core/session_control.py)),
  and the in-stream panel publishes no-op.

This measures the graph without transport noise — worker/WS overhead is not part of what
W5/W6 will be judged on.

**Tokens/latency/cost feed — the harness is the first consumer of S1's instrumentation.**
Run with `GRAPH_METRICS_ENABLED=true` in the harness's **own process** and read per-prompt
deltas straight from the prometheus default registry (sample-sum before/after each prompt,
sequential prompts ⇒ clean attribution; the `_sample` helper in
[tests/test_graph_metrics.py](../tests/test_graph_metrics.py) is the template). Wall
latency from a clock around `astream`; per-node from `tess_graph_node_duration_seconds`
deltas. **Import-order footgun:** `app.core.config` reads env at import and
`app/graph/observability.py` computes `_METRICS_ON` at import — the harness entrypoint
must set `os.environ` **before any `app.*` import** (top of
`scripts/graph_eval/__main__.py`, with a comment). Do NOT start servers or tracing —
in-process registry reads only. Judge-leg tokens come from
`LLMResponse.prompt_tokens/completion_tokens` (S1 commit 4) and are recorded as separate
judge-cost columns.

---

## Resolved question (b) — score stability / flake policy

- **The graph side is not temperature-pinned** — specialists call `create_llm()` bare
  ([app/agents/base.py:86](../app/agents/base.py)) → provider default temperature 0.7.
  Pinning it is a product change: **out of v1 scope**, filed as the escalation lever if
  flake proves bad (would add an eval-mode config knob; langchain-ollama `seed` support
  to be verified then, not assumed).
- **The judge IS pinned**: `create_llm(provider=cfg.judge_provider,
  config=LLMConfig(model=cfg.judge_model, temperature=0.0))` — the factory already takes
  both ([app/llm/factory.py:8-20](../app/llm/factory.py)).
- **Policy:** structural checks are strict, binary, artifact-based (completed panel
  exists; expected agents present; `mayor_data`/`usable_answers` counts; format checks;
  token/latency ceilings with generous margins). Judge scores are banded with margins;
  the run gate = all structurals pass AND judge score ≥ threshold, where every threshold
  is an executable claim with the house inline re-baseline comment.
- **Flake protocol** (the eval twin of harness-flake discipline): judge-band failure with
  all structurals green → one re-run of that prompt; two consecutive failures → treat as
  real. A re-run is the answer — never a threshold bump mid-arc. Optional
  `--judge-runs N` (median) exists for triage, default 1.

## Resolved question (c) — wall-time budget: measure before authoring

Measured S1 datum (this laptop, 4GB WSL, `llama3.2`): **one L0 turn ≈ 44 s cold**
(41.7 s direct_responder including model load; the follow-up call ran warm in ~2 s).
An L4 run is WR + specialists + combiners + defense + presenter, **strictly serialized**
by the Ollama request lock — plausibly 3–8 min per prompt. 25 prompts could be hours.

**Step 0 therefore measures ONE L4 prompt end-to-end in-process before any authoring**
(this same run proves the invocation path live). Then size the gates:
- **smoke set (~5 prompts, must include one L0, one L4, one escalation-tagged)** — the
  per-change gate, target ≲ 20 min;
- **full set (all prompts)** — the pre-PR / nightly-tier gate.
Both invoked explicitly (`run-all --set smoke|full`) with separate `--expect`-style
tallies — labeled gates, no silent weakening.

## Resolved question (d) — what "per-push signal" means in S2 (honest scope)

CI has no Ollama until S3 investigates runner-fit, so in S2 the eval gate is a **local
command** (exactly like the split-brain harness before nightly CI): run the smoke set
before any chain change, the full set before a chain-touching PR. What DOES run per-push
in CI is the harness's own unit layer (rubric engine on canned transcripts, tally/
threshold logic, set-composition checks — no LLM, part of the normal pytest suite).
Wiring any LLM-bearing eval leg into CI is **S3 scope**, stated here so nobody reads S2
as having delivered it.

---

## Golden set composition (v1 rules)

- `scripts/graph_eval/golden/` — data file(s) with a `set_version` field; loader +
  **composition unit tests**: every chain profile L0/L1/L1+/L2/L3/L4 present, every
  product mode present, ≥3 `escalation-required` tags, version present. Editing the set
  bumps `set_version` with the house inline re-baseline comment.
- **Media prompts: excluded from v1, with a comment in the set file.** Media agents are
  W6's prune-or-invest candidate — don't build a gate on a surface whose fate is
  undecided. Revisit at the W6 decision. (Override at session start if you want them in.)
- **Search realism:** on search-allowed profiles the graph may hit live
  DuckDuckGo/Tavily in-process. Rubrics must **never depend on live search content**
  (network flake ≠ chain regression); ceilings absorb search latency. A `--no-search`
  eval mode would need a product knob — deferred, noted.

## History schema (sqlite, minimums from the brief + identity)

- `runs`: run_id, ts_utc, git_commit, git_dirty, set_version, set_name(smoke|full),
  graph provider+model, judge provider+model+prompt_version, totals (prompts,
  structural_passed, judge_passed, prompt/completion tokens, cost_usd, wall_s), result.
- `prompt_results`: run_id, prompt_id, chain_profile, product_mode, structural_pass +
  failure list (json), judge_score, judge_verdict, prompt/completion tokens, cost_usd,
  latency_s, outcome.

## Steps (proposed commits — S2 session refines)

0. **Step 0** — merge PR #13, branch, baselines, provider sanity, **one-L4 measurement**,
   size smoke/full budgets.
1. **Harness core** — package skeleton (`config.py`, in-process runner, metrics-delta
   sampler, sqlite writer, structural rubric engine), `.gitignore` + `.dockerignore`
   entries same commit, unit tests on canned transcripts (no LLM, no docker; the
   cheap-harness-test template is
   [tests/test_splitbrain_topology_gate.py](../tests/test_splitbrain_topology_gate.py)).
2. **Golden set v1** — prompts + rubrics + composition tests.
3. **Judge leg** — pinned judge client, versioned judge prompt, strict/loud score
   parsing, identity recorded per run + row; smoke-set run green end-to-end.
4. **Run gates + non-vacuity + docs** — `--expect`-style tallies and thresholds as exit
   codes; **live sabotage proof** (temporarily force a wrong routing override in
   `app/graph/routing.py` → smoke score drops / structural agent-expectations fail →
   revert; recorded in the PR); harness README; NEXT_STEPS_PLAN §W2 progress note;
   CLAUDE.md rows + "run the eval gate before any chain change" sentence.

**Permanent non-vacuity (unit level, alongside the live proof):** rubric engine fed a
canned *wrong* transcript must fail; judge-output parser fed garbage must error loudly,
never silently pass; tally/threshold checkers unit-tested both directions.

**Acceptance** (from §W2): `python -m scripts.graph_eval run-all` prints per-prompt
scores + a tokens/latency/cost table; a deliberately broken chain fails the eval; a
history row lands with every identity field populated.

## House rules (unchanged)

Every guard gets a red-first proof; tallies/thresholds are executable claims with inline
re-baseline comments; suite + doc-links green per commit; PR into main (four required
checks now enforced), merge left to Jesse; heavy ops ladder not triggered — `app/**`
should be untouched this session except (if unavoidable) a tiny eval knob, and never
`app/ops/**` / `app/api/ops.py` / `scripts/ops_cp_splitbrain/**`.

## Environment notes

- Harness runs are strictly sequential (Ollama lock) — keep the laptop otherwise idle
  for timing stability; expect model reload cost after idle periods (the 44 s L0 datum
  was cold-load-dominated).
- PS 5.1 quote-mangling: commit/PR bodies via `git commit -F` / `--body-file`. `gh` at
  `C:\Program Files\GitHub CLI\gh.exe`.
- S3 runway after this session: `nightly.yml` (split-brain, offline chain, eval legs +
  runner-fit), s11 single-node variant stretch — see
  [W2_OPENER.md](W2_OPENER.md) §Session 3 runway.
