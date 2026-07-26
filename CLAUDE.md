# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TESS Engine is an event-driven AI orchestration engine. Users connect over a WebSocket; a Celery worker runs a LangGraph pipeline that streams "Panels" (status + content) back through Redis Pub/Sub. The graph fans out to **POV (point-of-view) agents** — one disciplinary lens per agent (chemistry, biology, economics, art, ui_design) — and optionally search. Combiners deduplicate and weave multi-POV output; Defense Review runs a QA pass before the Presenter packages a final Panel.

Detailed reference: `AI_MAP.md` (architecture), `SCHEMA.md` (data types), `ROADMAP.md` (phase history), `deploy/MULTI_CLOUD.md` (ops control-plane / HA). Historical per-phase and ops-hardening session briefs are archived under `docs/archive/phases/PHASE_*_OPENER.md` and `docs/archive/ops/`.

## Build, Lint, Test

```bash
# install Python deps
pip install -r requirements.txt

# run the full test suite (focused on logic, no live LLM)
pytest tests/

# run a single test file
pytest tests/test_pov_routing.py -v

# run a single test function
pytest tests/test_pov_routing.py::test_ionic_bonding_replaces_wrong_biology_pov -v

# quick smoke script (runs 3 routing tests)
python scripts/test_pov_routing.py

# frontend
cd frontend
npm install
npm run dev       # Vite dev server
npm run build     # tsc + vite build
npm run lint      # oxlint
```

## Local stack (Docker Compose)

```bash
cp .env.example .env
docker compose up --build    # web (FastAPI :8000), worker (Celery), redis
cd frontend && npm run dev   # Vite :5173 (or :5175)
```

Ollama must be running on the host (default `llama3.2`); Docker containers reach it via `host.docker.internal:11434` (already set in `docker-compose.yml`). See `LOCAL_DEV.md` for full setup including switching to Gemini.

## Deployment

Production server: `5.78.186.223` (Hetzner CPX11). Update via `ssh root@<server> "cd /opt/tess-engine && git pull && ./deploy/deploy.sh"`. See `deploy/DEPLOY.md` and `deploy/SERVER_CHECKLIST.md`.

**Offline / sovereign deploy (Step 4):** the full HA + observability stack packages into a
single `docker save` bundle that deploys and runs with zero outbound network, proven by the
split-brain harness `run-all` 10/10 under egress block. See `deploy/MULTI_CLOUD.md` §Offline
packaging (the Sovereignty Audit egress table lives there) and `deploy/offline/`
(`build-bundle.sh` → `install-offline.sh` → `verify-egress-blocked.sh`;
`docker-compose.offline.yml` is the self-contained, bind-mount-free, `internal:`-network
stack). Egress is blocked by engine-enforced internal networks, which also drop host
port-publishing, so the harness runs from an in-container runner reaching nodes by container
name. Non-root containers and a hash-pinned requirements lockfile are **deliberately
deferred** (documented in `deploy/MULTI_CLOUD.md` §Deferred hardening).

## Architecture

### Data flow

```
WebSocket (frontend) → FastAPI (app/api/ws.py) → Celery (app/worker.py)
  → compiled_graph.astream() (app/graph/builder.py)
  → Panels published to Redis channel_<session_id>
  → WebSocket forwards JSON to frontend
```

The frontend sends text or JSON envelope `{text, product_mode, chain_profile}` over `ws://<host>/ws/<session_id>`. Workers serialize each LangGraph node update into a `Panel` Pydantic model (see `app/graph/schemas.py`) and publish it. Frontend updates Panels in place by `panel_id`; intermediate "processing" panels share the same `panel_id` as the final "completed" panel.

### LangGraph nodes (app/graph/nodes/)

```
START
  ├─ L0  → direct_responder → presenter → END
  └─ L1+ → wide_receiver → fan_out (Send) ──┐
                                           ├─ <agent> (specialist) ──┐
                                           └─ resource_finder → resource_reader ──┤
                                                                                    ↓
                                                                       post_fan_in (waits for all branches)
                                                                                    ↓
                                                              ┌─ L1/L1+: presenter
                                                              ├─ L2/L3:   defense_delegator → defense_review → presenter
                                                              └─ L4:      combiner_mayor → combiner_micro → collector
                                                                          → defense_delegator → defense_review → presenter
```

- **wide_receiver**: LLM call returns JSON `{active_agents, current_task, search_queries}`. Routing post-processing in `app/graph/routing.py` (keyword override for wrong POVs, product-mode rules, chain-profile gates).
- **direct_responder**: L0 path — single LLM call, no specialists.
- **<agent> specialists**: `app/agents/base.py::run_specialist` runs an LLM call with the agent's system prompt + conversation history; produces a `MayorData` entry.
- **resource_finder → resource_reader**: DuckDuckGo / Tavily search, then page fetch + extract (`app/search/`).
- **combiner_mayor / combiner_micro / collector**: synthesize parallel `mayor_data` into ordered `UsableAnswer` segments.
- **defense_delegator / defense_review**: single LLM call evaluates each segment (big_picture / detail / implication); retries loop back to `combiner_micro` (or the originating specialist on bypass path); capped via `max_defense_retries(chain_profile)`.
- **presenter**: formats final Panel; runs follow-up chip generation (`follow_up_utils.py`), list-format post-processing (`list_format_utils.py`), and POV segment building (`pov_segments.py`).

### Chain profiles (L0–L4) and product modes

- `app/core/chain_profiles.py` — registry + validators + mode-to-profile defaults. Plain-text WebSocket input always resolves to L4.
- `app/graph/chain_gates.py` — pure gate functions (`allows_search`, `allows_defense`, `max_routed_agents`, etc.) keyed by chain profile. These are unit-tested directly.
- `app/core/product_modes.py` — `auto | research | planner | coding | builder`. Each mode injects routing rules into the WR system prompt and combiner/defense hints.
- WebSocket payload parsed in `app/core/ws_payload.py`.

### Specialist agent registry

`app/agents/registry.py::AGENT_REGISTRY` — dict of `AgentConfig` (name, folder_path, description, system_prompt, pov, agent_kind). Adding an agent: create `app/agents/<name>/{config.py,prompt.py}` and register the config. `app/agents/subjects/registry.py` holds POV definitions and keyword lists — keep `app/core/folder_tree.py` in sync with registry paths (`validate_tree_matches_registry()` is used in tests).

### LLM provider abstraction

`app/llm/factory.create_llm()` returns a `BaseLLM` (Gemini or Ollama). Selection via `DEFAULT_LLM_PROVIDER` env var. The Ollama wrapper (`app/llm/ollama.py`) serializes requests through an `asyncio.Lock` to prevent concurrent model calls on small hardware.

### Streaming and timing

- `app/worker.py::_run_graph_with_streaming` uses `astream(stream_mode="updates")` to publish Panels as each node completes. Soft time limit 720s, hard 730s (Celery).
- `app/graph/stream_utils.py::generate_with_panel_stream` — token-level streaming for L0 `direct_responder` and POV specialists; publishes `is_streaming` Panel deltas via Redis (throttled by `stream_throttle_ms`, default 75 ms).
- `app/core/session_control.py` — Redis-backed active task id + interrupt flag; WebSocket steer revokes in-flight Celery tasks when user sends while processing.
- `app/graph/panel_stream.py::publish_panel` — synchronous Redis publish from within async nodes (best-effort).
- Fan-in join via `expected_fan_in_branches` / `fan_in_branches_done` in `GraphState` (reducer-appended). `post_fan_in` waits until all branches complete; `fan_in_wait` is a no-op sink for early branches.

## Key Conventions

- **All new graph state** must be declared in `app/graph/state.py::GraphState` and added to `_REDUCER_KEYS` in `app/worker.py` if it should append-merge from parallel branches.
- **All Panel additions** are optional with sensible defaults — frontend `frontend/src/types/panel.ts` should mirror them.
- **POV agents** are disciplinary lenses, not depth variants. New POV: add to `POV_DEFINITIONS` in `app/agents/subjects/registry.py`, create `app/agents/<key>/`, register in `app/agents/registry.py`, mirror in `app/core/folder_tree.py` and `frontend/src/data/folderTree.ts`.
- **Linter** on frontend: `oxlint`; type-check via `tsc -b` (run as part of `npm run build`).
- **No Cursor rules** (`.cursor/` absent) — `.cursorrules` contains a short set: production-ready typed/Pydantic code, async-first FastAPI, modular layout, Celery delegation for heavy AI work, English-only docs and user-facing strings.
- **Tests are unit-level** — they exercise routing/parsing/serialization utilities directly, not the live graph. Live integration testing is via the local Docker stack (see `LOCAL_DEV.md`).

## Ops control-plane HA — critical invariants

The ops control plane supports an etcd-leased primary/standby pair (overlay:
`docker-compose.ops-ha.yml`; default deploy has `OPS_HA_ENABLED=false`, so this is inert
unless HA is switched on). `deploy/MULTI_CLOUD.md` is the authoritative contract. When
touching the ops/HA path (`app/ops/`, `app/api/ops.py`, `app/worker.py` ops tasks), these
rules must not be violated — they are enforced by `tests/test_ops_fencing.py` and the
split-brain harness:

- **All durable ops writes go through the fence.** `persist_store()` (`app/ops/store.py`)
  writes through the authoritative `FenceStore` selected by `ops_fence_authority`
  (**default `etcd`** post-cutover: one linearizable etcd txn-CAS over the fence term +
  durable blob; `redis` is the legacy Lua-CAS backend, used only when opted back in via
  `ops_fence_authority=redis`). Never write the durable blob (`REDIS_CONTROL_PLANE_KEY` /
  the etcd blob key) directly.
- **Every mutating `/ops/*` durable write goes through one serialized offload.** All durable
  writes in `app/api/ops.py` route through `_fenced_commit` / the process-wide
  `_mutation_lock` (`asyncio.to_thread` so the CAS / etcd-failover ladder never stalls the
  event loop; the lock so two writers can't race a lost update under one fence term — CAS
  fences terms, not writers within a term). **Full coverage is required** — the async-helper
  handlers (`compare`, `byo`) hold the same lock directly (a coroutine can't be
  `to_thread`-ed). Partial coverage reopens a cross-path lost-update race. Enforced by
  `tests/test_ops_mutation_lock.py` (two-writer serialization, proven non-vacuous).
- **A CAS rejection is as severe as an etcd rejection: demote + raise.** `FenceCasError`
  is never downgraded to a warning.
- **Celery ops tasks use `check_fence_live()` only** (`app/ops/fencing.py`) — a fresh etcd
  leader/term check, never cached web role state. `require_primary_cached` and
  `get_role_state` are banned *in `app/worker.py`*; `tests/test_ops_fencing.py` statically
  asserts their absence and that `check_fence_live` runs in each ops task. (The HTTP layer
  deliberately uses cached role in its mutation gate — see below — so the ban is worker-only.)
- **Mutating `/ops/*` endpoints 503 on standby with the fence body.** The router-level
  `_gate_ops_mutations` dependency (`app/api/ops.py`) runs *before* per-endpoint auth
  (`require_admin`); reads (GET/HEAD/OPTIONS) and `/ops/ha` stay available.
- **Split-brain harness:** `python -m scripts.ops_cp_splitbrain run-all`. Assertions target
  artifacts (Redis term/blob, pubsub, HTTP bodies), never log strings. A harness failure is a
  product bug until proven otherwise — fix the product, don't soften the assertion.
- **Verified baseline:** the Quorum Fence Store arc (`cursor/cp-ha-quorum-fence-store`) built
  the etcd cutover on CP HA v1 (`84b81f5`): Step 1 (`6331b00`) `FenceStore` seam, Step 2
  (`315b044`) `EtcdFenceStore` + parity, Step 3 (`3a3444a`) 3-node etcd quorum, Step 4
  (`3e72fbe`) bounded shadow dual-write, **Step 5a** flipped the default to **etcd authority**
  (`ops_fence_authority="etcd"`) with a bounded reverse shadow, the ops.py mutation-lock
  offload, and an authority-aware harness, **Step 6** added the leader-kill mutation-storm
  scenario (`s11`: SIGKILL the etcd Raft leader mid-storm — durable writes block-and-resume on
  the new leader within bound, monotonic term, no split-brain; a Raft-term-advanced guard
  proves the re-election gap was real — and, while the shadow still existed, `diverge==0` with
  `match` advanced under the storm), and **Step 5b** (arc closer) **retired the dual-write /
  reverse shadow** — the shadow machinery, the `ops_fence_shadow` config, the shadow metric,
  and the migration-era read-only Redis restore fallback are gone (an absent etcd blob now
  triggers loud explicit recovery, never silent Redis adoption). etcd is the sole durable
  store; Redis is caches + pub/sub, with `ops_fence_authority=redis` as the pure opt-in legacy
  backend. The harness is **11 scenarios**. Any change to `app/ops/consensus.py`,
  `app/ops/fencing.py`, `app/api/ops.py`, or the `store.py` `FenceStore` path requires
  re-running, before commit: the split-brain harness (**defaults to `authority=etcd`** — a
  plain `run-all` is the etcd cutover; `OPS_FENCE_AUTHORITY=redis run-all` exercises the legacy
  backend), `tests/test_ops_fencing.py`, and the live-etcd parity suite
  (`tests/test_fence_store_parity.py` against a real etcd — a plain `pytest tests/` **skips**
  the etcd contract, so green alone does not prove the etcd backend). See
  `docs/archive/ops/CP_HA_QUORUM_OPENER.md` § Verification.
- **Unelectable limitation — resolved by the etcd cutover.** The old "external Redis
  fence bump → cluster unelectable until Redis reset" trap is **gone under the default `etcd`
  authority**: the fence term and durable blob are one linearizable store, so a term
  perturbation just re-syncs the primary (proven by split-brain `s07`/`s08` under etcd — no
  split-brain, monotonic term, no durable corruption). It still applies to the **legacy
  `redis` backend** (`ops_fence_authority=redis`), where the two term stores can diverge — so
  don't "fix" the redis path casually; it is retained only as the opt-in rollback backend.
- **Observability cardinality discipline (`app/ops/metrics.py`).** Metrics/traces are
  self-hosted, opt-in, OFF by default (`OPS_METRICS_ENABLED` / `OPS_TRACING_ENABLED`). Every
  metric label value must be a **fixed code enum or per-process constant** — `provider_id`
  (unbounded uuid) and session ids / URLs / error strings are **banned** as labels; use
  `provider_type` instead. `tests/test_ops_metrics.py` enforces the label allowlist. Worker
  metric exposition assumes the worker runs `--concurrency=1` (see `deploy/MULTI_CLOUD.md`
  §Observability). `record_*` helpers never raise. Scope is the ops/HA path only — do **not**
  instrument the product graph. Verified end-to-end by split-brain scenario
  `s10_failover_visible` (needs `docker-compose.ops-obs.yml`).

## Common file pointers

| Concern | File |
|---|---|
| Graph wiring | `app/graph/builder.py` |
| Chain profile gates | `app/graph/chain_gates.py` |
| Routing + keyword overrides | `app/graph/routing.py` |
| Presenter / final Panel | `app/graph/nodes/presenter.py` |
| Worker + Redis publish | `app/worker.py` |
| WebSocket endpoint | `app/api/ws.py` |
| Frontend WebSocket hook | `frontend/src/hooks/useWebSocket.ts` |
| Frontend Panel type | `frontend/src/types/panel.ts` |
| Status wall logic | `app/graph/pipeline_stages.py` + `frontend/src/hooks/usePipelineStatus.ts` |
| Folder tree | `app/core/folder_tree.py` + `frontend/src/data/folderTree.ts` |
| POV segment builder | `app/graph/pov_segments.py` |
| Follow-up generator | `app/graph/follow_up_utils.py` |
| List format | `app/graph/list_format_utils.py` |
| Search | `app/search/provider.py` + `app/graph/nodes/resource_*.py` |
| Ops control-plane HA | `app/ops/consensus.py`, `app/ops/fencing.py`, `app/ops/store.py` |
| Ops HTTP endpoints + mutation gate | `app/api/ops.py` |
| Ops fencing invariants (tests) | `tests/test_ops_fencing.py` |
| Split-brain harness | `scripts/ops_cp_splitbrain/` |
| Ops observability (metrics/traces) | `app/ops/metrics.py` + `deploy/MULTI_CLOUD.md` §Observability |
| Ops metrics cardinality guard (tests) | `tests/test_ops_metrics.py` |
| Observability verification overlay | `docker-compose.ops-obs.yml` + `deploy/otel-collector-config.yaml` |
| Offline / sovereign stack | `docker-compose.offline.yml` + `deploy/offline/` (`build-bundle.sh`, `install-offline.sh`, `verify-egress-blocked.sh`) |
| Sovereignty audit + offline runbook | `deploy/MULTI_CLOUD.md` §Offline packaging |
