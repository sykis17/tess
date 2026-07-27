# W3 — Handoff notes from the W2 Session 2 session (2026-07-27)

Notes to **fold into the W3 opener**, not the opener itself. Written at PR #14's head
(`a8ccdbe`) by the session that built the eval harness, plus an oversight-review brief.
Filing: [NEXT_STEPS_PLAN.md §W3](NEXT_STEPS_PLAN.md). Everything below is **verified
against the installed langgraph and the repo at `a8ccdbe`** — file:line refs, not memory.
The next session's first job is to expand §W3 into a full opener
([NEXT_STEPS_PLAN.md:425-427](NEXT_STEPS_PLAN.md) names that step).

Two of the plan's open questions moved. **Question (b) resolved favourably** — the
no-double-execution guarantee is built into the pinned langgraph, not something to build.
**Question (a) moved decisively** toward custom-over-Redis on dependency grounds. Three
traps nobody had named are below; two of them silently corrupt rather than fail loud.

---

## Start state (verify first)

1. **PR #14 must be merged first** (`ops/w2-s2-graph-eval` — these notes ride it as the
   final commit, the same way the S2 opener rode PR #13). `git checkout main && git pull`,
   confirm the merge, then `git switch -c graph/w3-checkpointing`.
2. `python -m pytest tests/ -q` → **377 passed, 2 skipped**.
   `python -m scripts.check_doc_links` → **0 broken** (~520 links).
3. **The eval gate now applies to this workstream.** `app/graph/builder.py` is
   `app/graph/**`, so **every W3 commit is a chain change**:
   `python -m scripts.graph_eval run-all --set smoke --expect-pass 5` before each,
   `run-all --expect-pass 20` before the PR. Budget from measured runs: smoke ≈ 3.5 min
   graph wall, full ≈ 25 min (1492 s, ~180k tokens). Ollama up, no docker.
4. **Venv has drifted from the lock** — `langchain-core` 1.4.9 installed vs **1.5.1**
   locked; `langchain-google-genai` 4.2.7 vs 4.3.1. `pip check` is clean, but anything
   validated locally is validated against 1.4.9. Reconcile before trusting a serializer
   round-trip result.
5. `docker ps` — nothing should be running.

---

## Doctrine classification (settle this in one paragraph, first thing)

Post-cutover doctrine is "**Redis = caches + pub/sub only**"
([CLAUDE.md](../CLAUDE.md) §Ops control-plane HA). Checkpoints are doctrine-**compatible**
if and only if they are classified as **recoverable-loss data**: a lost checkpoint means a
run restarts — never corruption, never split authority. Write that classification down
explicitly, or W3 reads as violating the W2-era contract.

**etcd is not a candidate** — 1.5 MiB request limit and a quorum write per checkpoint
would abuse the coordination store. The fence store's linearizable guarantees are for
authority, not for run scratch.

---

## Five traps (two of them corrupt silently)

**1. `thread_id` per TURN, not per session — confirmed, with the exact failure.**
LangGraph re-invoked with an existing `thread_id` continues from that thread's last
checkpoint. If `thread_id = session_id`, turn 2's fresh state **merges into** turn 1's
persisted channels via the `operator.add` reducers. The concrete break:
`fan_in_branches_done` inherits turn 1's entries, so
[app/graph/fan_in_utils.py:21-25](../app/graph/fan_in_utils.py)
`all_fan_in_branches_complete()` returns True prematurely and the join fires **before this
turn's branches finish**. A second visible symptom: `panel_id` carryover makes turn 2
overwrite turn 1's rendered row in the UI.

The fix needs **zero new plumbing**: `panel_id`
([app/worker.py:295](../app/worker.py), `str(uuid.uuid4())` per turn) is the only per-turn
UUID in the app and is already in `GraphState`. Use `thread_id = f"{session_id}:{panel_id}"`.
The Celery task id would work semantically but is not in state and would need threading
through `build_initial_state` — and would break the eval-harness caller, which passes
`session_id=""`. A state-leak repro (two sequential turns, same session, turn 2 starts
clean) is cheap and belongs in the gate set.

**2. The eval harness must stay zero-infra.**
[scripts/graph_eval/runner.py](../scripts/graph_eval/runner.py) imports `compiled_graph`,
and [app/graph/builder.py:84](../app/graph/builder.py) builds it as a **module-import-time
singleton**. An unconditional `compile(checkpointer=...)` constructs a Redis-connected
saver at import in every process — including the harness, which has no Redis and no
session. The compile needs a seam (checkpointer injected or flag-gated), default OFF
(`graph_checkpointing_enabled=False`), worker enabling it via config. **Gate: S2 smoke 5/5
still green with W3 merged and flags off.** Note `build_graph()` is already a function
([builder.py:43](../app/graph/builder.py)) — parameterizing it and making the singleton
lazy is the natural shape.

**3. `decode_responses=True` will corrupt checkpoints — silently.**
Both factories in [app/core/redis.py:14-21](../app/core/redis.py) build clients with
`decode_responses=True`. The default serializer emits **msgpack bytes** (see trap 5), and
decoding those as UTF-8 str corrupts them. W3 needs its own client or a
`decode_responses=False` variant — **do not reuse `create_sync_redis()` as-is.**

**4. Resumed token streams double the visible answer.**
[frontend/src/hooks/useWebSocket.ts:52-87](../frontend/src/hooks/useWebSocket.ts)
`mergePanelUpdate` **concatenates** content when `is_streaming: true` and replaces when
false. So a duplicate *terminal* panel is harmless (idempotent replace), but a resumed
*streaming* panel appends its tokens onto the pre-interrupt partial content — visibly
doubled text, with no sequence number, offset, or reset signal in the protocol to recover.
This is worse than the "duplicate panels" framing: it corrupts rather than repeats.

Compounding it: panels publish by **two** paths. Post-node in the worker
([app/worker.py:272-274](../app/worker.py)) and **mid-node directly** via
[app/graph/panel_stream.py](../app/graph/panel_stream.py) — called from eight nodes plus
every token batch in `stream_utils.py` and every heartbeat in `progress_utils.py`. Path B
side effects never enter graph state, so **no state-based dedup can see them**. Decide the
delivery guarantee explicitly (at-least-once + client dedup is probably the honest one),
and note `Panel` has no reset flag today ([app/graph/schemas.py:105-125](../app/graph/schemas.py))
— adding one, or making `panel_id` run-scoped, is the lever.

**5. The serializer degrades to `dict` without raising.**
`JsonPlusSerializer` is **msgpack-first despite the name**. On decode it re-imports the
class and, on *any* reconstruction failure, **returns the raw kwargs dict** — no
exception. Your node then gets a plain `dict` where a `Panel` is expected and blows up far
from the cause. Separately, app classes are not in the serializer's safe-types allowlist:
default (permissive) mode reconstructs them but emits a deprecation warning per type
(*"will be blocked in a future version"*), and `LANGGRAPH_STRICT_MSGPACK=true` returns
plain dicts instead. Decide `allowed_msgpack_modules` in W3 rather than eating the
warning, and write a **round-trip test over every model in
[app/graph/schemas.py](../app/graph/schemas.py)** — all eight state-carried types are
Pydantic v2 (`AgentTrace`, `SearchResult`, `MayorData`, `MicroData`, `UsableAnswer`,
`DefenseReview`, `Panel`, plus `LLMMessage`).

---

## Design questions, grounded in code

**(a) Backend — the dependency arithmetic decides it.** `langgraph-checkpoint` **4.1.1 is
already a transitive dep** (`requirements.lock.txt:680`): `BaseCheckpointSaver`,
`InMemorySaver`, and `JsonPlusSerializer` all ship today. `langgraph-checkpoint-redis` is
**not** present — adding it means a lock regeneration whose header command is
**unrunnable as written** (it references `current-freeze.txt`, which is not in the repo;
the real procedure is [deploy/MULTI_CLOUD.md:378-383](../deploy/MULTI_CLOUD.md)), plus an
offline-bundle rebuild and a stale "103 pkgs" count to re-baseline. A custom
`BaseCheckpointSaver` over the existing `redis` dep costs **zero new packages**. House
precedent points the same way twice: `EtcdHttpConsensus` (own thin critical code over
dependency rot) and *"protecting the lock beats convenience"*
([W2_OPENER.md:76-78](W2_OPENER.md), the pytest-asyncio refusal). State it as a settled
decision with that evidence, not a preference. Note `BaseCheckpointSaver` is **not an
ABC** — a partially-implemented saver instantiates fine and fails at runtime.

**(b) Pending writes — RESOLVED: built in, given a correct saver.** In the pinned
langgraph 1.2.9 the loop persists each task's writes as it completes (`_runner.py:609-613`,
including a `NO_WRITES` sentinel so a node returning nothing still records "I ran"), and on
resume `_reapply_writes_to_succeeded_nodes` (`_loop.py:736`) rehydrates them, after which
only tasks where `not t.writes` are ticked (`main.py:2967`). So **"resume without
double-executing a completed fan-out branch" is a framework guarantee** — what W3 builds is
only the durable saver (correct `put_writes` keyed by `task_id`, `pending_writes` populated
on `get_tuple`). Three caveats to write down: a saver that stubs `put_writes` makes every
branch re-execute; `durability="exit"` **disables `put_writes` entirely** (`_loop.py:466`) —
W3 wants `"sync"`, and it is a per-invocation arg, not a `compile()` one; failed and
interrupted tasks **do** re-run by design, which is the contract, not a bug. Storage should
be idempotent on `(thread_id, checkpoint_id, task_id, idx)`.

**(c) Panel replay on resume** — see trap 4. The design question is the delivery guarantee
and whether streaming panels get a reset affordance.

**(d) Metrics semantics** — there is **no outcome enum and no test bounding outcome
values** in the graph plane, so adding `"resumed"` would be silent (contrast the ops twin,
which does bound it). The house move is to add the guard in the same commit. Re-baseline
sites if resumed runs should appear in latency trends:
[tests/test_graph_metrics.py](../tests/test_graph_metrics.py) `test_duration_histograms_record_success_only`
and `test_run_duration_success_only`, plus the success-only policy stated in
[app/graph/observability.py](../app/graph/observability.py), [W2_OPENER.md](W2_OPENER.md),
and [CLAUDE.md](../CLAUDE.md). **`thread_id` must never become a metric label** — it is
`session_id`-derived and therefore unbounded; add it to the banned list alongside
`trace_id`/`request_id`. Span attribute only.

**(e) TTL/eviction** — checkpoints × supersteps × sessions accumulate in Redis on a 4 GB
VM. Measure one L4 run's checkpoint weight in **Step 0** (same measure-before-authoring
move that S2 used for wall-time), then set `graph_checkpoint_ttl_seconds` from config. The
only `setex` precedent in the repo is [app/search/cache.py:36-48](../app/search/cache.py).
Worth noting while you're there: `conversation:{session_id}`
([app/core/conversation.py](../app/core/conversation.py)) has **no TTL at all** — unbounded,
capped only at 20 messages.

---

## Existing continuity: don't build a second history store

Cross-turn continuity is **already solved** by `conversation:{session_id}`, written once at
the end of a successful turn ([app/worker.py:320](../app/worker.py)) and read back into
fresh state each turn. A checkpointer would persist the same conversation on a different
write schedule (every superstep, including turns that never completed), so the two can
diverge — a checkpoint could carry a turn the rest of the system never recorded. Keep
`conversation:{session_id}` as the single source of truth and make the checkpoint thread
**strictly per-run**, ephemeral, never outliving the turn that owns it.

Three things are **session-scoped today** and need run-scoping for resume to be safe: the
interrupt flag (`session:{sid}:interrupt`, cleared unconditionally by the *next* turn at
[app/worker.py:291](../app/worker.py) — a fast turn N+1 can clear the flag turn N was
supposed to observe), the active-task record, and the frontend's `panel_id` merge key.

---

## Gates (red-first each, per house rules)

- **Resume**: interrupt mid-fan-out → resume → coherent final Panel, no branch
  double-executes. **Must fail with the checkpointer removed or the flag off.**
- **State leak**: two sequential turns, same session — turn 2 starts clean (this is trap 1's
  executable form).
- **Flags-off inertness**: S2 eval smoke **5/5 with checkpointing off**, proving the
  zero-infra path intact; plus a unit passthrough test modeled on
  `test_instrument_node_flags_off_is_passthrough`.
- **Serialization round-trip**: every Pydantic model in `app/graph/schemas.py` survives
  dumps→loads as its class, **not** as a dict (trap 5's executable form).
- **Replay**: reproduces the same node sequence (the plan's own acceptance).
- **Reducer sync**: `_REDUCER_KEYS` ([app/worker.py:127-134](../app/worker.py)) is a
  hand-maintained shadow of the `Annotated[..., operator.add]` declarations in
  [app/graph/state.py:18-43](../app/graph/state.py) — six keys each, agreeing today, with
  **no test asserting they agree**. A checkpointer has to satisfy both; this is the natural
  place to make that an executable claim rather than a comment.

Two guard hazards to route around: `tests/test_graph_metrics.py` reads
[app/graph/builder.py](../app/graph/builder.py)'s **source text** to assert every
`add_node` routes through `instrument_node` (with a `>= 13` count) — editing builder.py can
trip it, and any node W3 adds must be wrapped. And a brand-new metric object must be
appended to `ALL_GRAPH_METRICS` or every cardinality guard goes **silently vacuous** for it
(there is no completeness test — a real gap worth naming).

---

## W4 forward-pointer (don't solve, don't preclude)

Migration = resume on a **different provider**, so W4 needs the checkpoint readable from
the target. Per-provider Redis makes that a W4 problem (cross-provider transport, or
copy-on-migrate). W3's only obligation is that the saver sits **behind a seam**, so the
backend can evolve without re-touching call sites.

---

## W2 Session 3 — deferred, not dropped (owner: the session after W3)

Going to W3 now is a sound resequencing: W3 blocks W4 and enriches W5, while nightly CI
blocks nothing. But it is being said out loud here and in
[NEXT_STEPS_PLAN.md §W2](NEXT_STEPS_PLAN.md) because **the offline verifier rotted
precisely because a verification step was deferred without a recorded owner** — the program
should not repeat that with its own nightly wiring. S3's scope is unchanged and still
filed at [W2_OPENER.md §Session 3 runway](W2_OPENER.md): nightly legs (split-brain, offline
chain, eval judge), runner-fit, and the `s11` single-node stretch.

**Irony insurance:** until S3 lands, the eval doctrine — smoke before chain changes, full
set before chain PRs — is **manual discipline**, which is exactly the state CI exists to
end. W3 is the first workstream to run under that manual gate on every commit.

---

## Decisions to settle before the W3 opener is final

1. **Backend** — custom `BaseCheckpointSaver` over the existing `redis` dep (zero new
   packages) vs `langgraph-checkpoint-redis` (lock regen + offline rebuild). Evidence in
   (a) points one way; confirm it.
2. **Doctrine classification** — checkpoints as recoverable-loss data, in writing.
3. **`durability` mode** — `"sync"` vs `"async"` (default), given `"exit"` forfeits the
   resume guarantee.
4. **Serializer allowlist** — register `app.graph.schemas` types now, or accept the
   deprecation warning.
5. **Panel delivery guarantee on resume** — at-least-once + client dedup, vs a reset
   affordance on the Panel schema.
6. **Metrics semantics** — new `graph.run` with a `"resumed"` outcome (plus a bounding
   guard) vs continuation.
7. **TTL** — value, after the Step 0 checkpoint-weight measurement.

## Environment notes

- Same laptop profile as S2: strictly sequential Ollama, `llama3.2`, no docker needed for
  the unit layer. The eval gate on every commit is the new time cost — budget ~3.5 min per
  smoke run.
- PS 5.1 quote-mangling: commit/PR bodies via `git commit -F` / `--body-file`. `gh` at
  `C:\Program Files\GitHub CLI\gh.exe`.
- [NEXT_STEPS_PLAN.md §W3](NEXT_STEPS_PLAN.md) cites `builder.py:78` for the bare
  `compile()`; it is now **[builder.py:81](../app/graph/builder.py)** — fixed in this
  commit.
