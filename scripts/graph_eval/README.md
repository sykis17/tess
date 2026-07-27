# Graph eval harness

Repeatable eval gate for the product graph: a versioned golden set
([golden/set_v1.json](golden/set_v1.json)) runs through `compiled_graph`
**in-process** (zero infra — no Redis, no worker, no docker; `session_id=""`
makes every transport side-effect inert), scored by strict structural rubrics
plus a pinned LLM judge, with per-run history in sqlite. Design and settled
decisions: [../../docs/W2_S2_OPENER.md](../../docs/W2_S2_OPENER.md); filing:
[../../docs/NEXT_STEPS_PLAN.md](../../docs/NEXT_STEPS_PLAN.md) §W2.

## The gate

**Run the smoke set before any chain change; run the full set before a
chain-touching PR.** The expected tallies are executable claims:

```bash
python -m scripts.graph_eval run-all --set smoke --expect-pass 5   # per-change gate
python -m scripts.graph_eval run-all --expect-pass 20              # pre-PR gate (--set full is the default)
python -m scripts.graph_eval run <prompt_id>                       # triage one prompt (no history row)
python -m scripts.graph_eval list
```

Exit code: real failures dominate; an `--expect-pass` mismatch independently
flips a green run to 1 (tally as exit-code artifact, never a log-grep — the
tally prints on every run, with or without an expectation). Re-baselining a
tally is a deliberate event: bump `set_version`, update the composition
constants in [../../tests/test_graph_eval_golden.py](../../tests/test_graph_eval_golden.py),
note it in the commit.

## Prerequisites

- Host Python env with `requirements.txt` installed; run from the repo root.
- Ollama on the host with `llama3.2` (`curl localhost:11434/api/tags`).
- `.env` resolving `DEFAULT_LLM_PROVIDER=ollama` with a host-reachable
  `OLLAMA_BASE_URL` — the harness **asserts and records** the resolved graph
  provider/model at startup, and refuses to run if the in-process metrics feed
  is off (it would record a zeroed run).
- Keep the laptop otherwise idle: prompts run strictly sequentially behind the
  Ollama request lock, so wall times are the measurement.

## Budgets (baselined 2026-07-27, this laptop, warm llama3.2)

| run | graph wall (measured) |
|---|---|
| one L4 prompt | 80–230 s (heaviest: `l4_science_fair`) |
| smoke (5 prompts) | ~3.5 min |
| full (20 prompts) | ~25 min (1492 s graph wall, ~180k tokens) |

Wall times vary by 2× run to run on the same prompt — the Ollama lock plus
model-reload cost dominate. Size expectations off the upper end.

Cold model load adds ~30–40 s to the first prompt. Search-bearing prompts
(L3/L4) absorb live DuckDuckGo/Tavily latency inside their ceilings.

## Scoring

- **Structural rubrics** (strict, binary, artifact-based — [rubrics.py](rubrics.py)):
  completed panel exists; expected agents present in `mayor_data`; min counts;
  content non-empty; `content_type`/`content_format`; token/latency ceilings.
  Rubrics never assert on live search content — network flake is not a chain
  regression.
- **LLM judge** ([judge.py](judge.py)): pinned `temperature=0.0`, default
  Ollama-local (zero spend), provider/model via `GRAPH_EVAL_JUDGE_PROVIDER` /
  `GRAPH_EVAL_JUDGE_MODEL`. The judge prompt is versioned
  (`JUDGE_PROMPT_VERSION`); judge identity is recorded in every history row.
  The parser is strict and loud — garbage raises, it can never silently pass.
  Threshold: `JUDGE_PASS_THRESHOLD` in [config.py](config.py) (banded under
  the observed smoke floor; re-baseline deliberately, never mid-arc).
- A prompt passes when **all structurals pass AND judge score ≥ threshold**.
- **Observed judge limit** (sabotage run, 2026-07-27): the 3B local judge
  scores fluent wrong-lens answers 8–9 — routing regressions are caught by the
  **structural** layer, not the judge; the judge gates answer quality. A
  stronger judge via `GRAPH_EVAL_JUDGE_PROVIDER`/`_MODEL` is the escalation
  lever if judge discrimination needs to carry more weight.

## Flake protocol (the eval twin of harness-flake discipline)

Exactly two covered flake classes, one automatic re-run each, two consecutive
failures are real (`attempts=2` recorded in history):

1. **Judge-band miss (or judge parse error) with all structurals green.**
2. **Structural failure on a search-allowed profile (L3/L4)** — a transient
   search failure can miss min-counts with no chain regression.

Structural failures elsewhere get no retry: nothing external runs there. A
re-run is the answer — never a threshold bump mid-arc. `--judge-runs N`
(median) exists for triage, default 1.

A **runaway-chain guard** aborts any prompt at its rubric's `max_wall_s`
ceiling (outcome `timeout`, structural red, partial state kept). It exists
because the harness's first live run caught a real unbounded defense retry
loop on L3 — see `tests/test_defense_routing.py` for the regression guards.

## History (sqlite)

`history.db` (gitignored + dockerignored; override with
`GRAPH_EVAL_HISTORY_DB`): `runs` carries git commit + dirty flag, set
name/version, graph provider/model, judge provider/model/prompt-version, and
totals (tokens, cost, wall, structural/judge pass counts); `prompt_results`
carries per-prompt structural failures (json), judge score/verdict, graph and
judge token/cost columns (never mixed — graph deltas are sampled before the
judge leg), latency, outcome, attempts.

## Per-push honesty (S2 scope)

Only the harness's **no-LLM unit layer** rides per-push CI
(`tests/test_graph_eval_*.py`: rubric engine on canned transcripts, tally and
retry logic, CLI wiring, loader and composition guards, runaway-guard tests).
The LLM-bearing smoke/full runs are local commands — wiring any eval leg into
CI (runner-fit, nightly tier) is **W2 Session 3 scope**.

## Editing the golden set

Media prompts are excluded from v1 (W6 prune-or-invest decision pending — the
exclusion note lives in the set file). Any edit bumps `set_version`, keeps the
composition rules green (every profile L0–L4 incl. L1+, every product mode,
≥3 `escalation-required` tags, smoke ⊆ full), and re-baselines the tallies —
silent set edits are a test failure by construction.
